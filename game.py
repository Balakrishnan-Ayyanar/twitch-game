"""Deterministic authoritative mission simulation; no network dependencies."""
from collections import deque
import time

WIDTH, HEIGHT = 13, 9
ROADS = {(x, y) for x in range(1, 12) for y in (2, 4, 6)} | {(x, y) for x in (1, 5, 9, 11) for y in range(2, 7)}
BASE, CREW, SHELTER = (1, 6), (11, 2), (11, 6)
OPTIONS = [
    {'id': 'north', 'title': 'North bridge', 'detail': 'Open north crossing. No resource cost.', 'command': '!north'},
    {'id': 'scan', 'title': 'Scan central', 'detail': 'Open central crossing. +8s oxygen, −4 battery.', 'command': '!scan'},
    {'id': 'supply', 'title': 'Supply drop', 'detail': 'Open south crossing. +22 battery, −6s oxygen.', 'command': '!supply'},
]

def shortest_path(start, goal, blocked=()):
    blocked = set(blocked)
    if start not in ROADS or goal not in ROADS or start in blocked or goal in blocked:
        return []
    queue, parent = deque([start]), {start: None}
    while queue:
        node = queue.popleft()
        if node == goal:
            route = []
            while node is not None:
                route.append(node)
                node = parent[node]
            return route[::-1]
        x, y = node
        for nxt in ((x+1,y), (x,y-1), (x,y+1), (x-1,y)):
            if nxt in ROADS and nxt not in blocked and nxt not in parent:
                parent[nxt] = node
                queue.append(nxt)
    return []

class Game:
    ROUND_SECONDS = 7.0
    STEP_SECONDS = 1.25

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.epoch = 0
        self.restart()

    def restart(self):
        self.epoch += 1
        self.status = 'ready'
        self.position = BASE
        self.carrying = False
        self.battery = 42.0
        self.oxygen = 65.0
        self.bridge = 4
        self.round = 1
        self.votes = {}
        self.round_left = self.ROUND_SECONDS
        self.move_left = self.STEP_SECONDS
        self.elapsed = 0.0
        self.last = self.clock()
        self.last_decision = None
        self.events = []
        self.log('Control', 'Mission ready. A supply vote is needed to cover the full journey.')

    @property
    def token(self):
        return '{}:{}'.format(self.epoch, self.round)

    @property
    def blocked(self):
        # Never close a crossing beneath the rover.
        return {(7, y) for y in (2,4,6) if y != self.bridge and (7,y) != self.position}

    def route(self):
        return shortest_path(self.position, SHELTER if self.carrying else CREW, self.blocked)

    def log(self, who, message):
        self.events.append({'who': who, 'message': message})
        self.events = self.events[-16:]

    def start(self):
        if self.status == 'ready':
            self.status = 'running'
            self.last = self.clock()
            self.log('Control', 'Rover deployed. Vote now; the route updates when the round closes.')

    def vote(self, viewer, option, token, source="simulated"):
        if self.status != 'running':
            return False, 'Start a mission before voting.'
        if token != self.token:
            return False, 'That round has closed. Vote in the current round.'
        if option not in [o['id'] for o in OPTIONS]:
            return False, 'Unknown action.'
        if not isinstance(viewer, str) or not viewer.strip() or len(viewer) > 40:
            return False, 'Viewer name must contain 1–40 characters.'
        viewer = viewer.strip().casefold()
        if viewer in self.votes:
            return False, 'One vote per viewer per round.'
        self.votes[viewer] = option
        self.log('Twitch viewer' if source == 'twitch' else viewer, '!'+option+(' · Twitch chat vote' if source == 'twitch' else ' · simulated vote'))
        return True, 'Vote accepted.'

    def resolve_round(self):
        counts = {o['id']: list(self.votes.values()).count(o['id']) for o in OPTIONS}
        # Stable displayed order wins ties, including an empty round.
        winner = max(counts, key=counts.get)
        before = (self.battery,self.oxygen,len(self.route())-1)
        reason = 'no_votes' if not self.votes else 'tie' if list(counts.values()).count(counts[winner]) > 1 else 'most_votes'
        if winner == 'north':
            self.bridge = 2
            effect = 'North bridge opened; other crossings closed.'
        elif winner == 'scan':
            self.bridge = 4
            self.oxygen += 8
            self.battery -= 4
            effect = 'Central crossing scanned: +8s oxygen, −4 battery.'
        else:
            self.bridge = 6
            self.battery = min(100, self.battery + 22)
            self.oxygen -= 6
            effect = 'South supply drop: +22 battery (cap 100), −6s oxygen.'
        self.last_decision = {'round':self.round,'action':winner,'counts':counts,'reason':reason,
            'battery_delta':round(self.battery-before[0],1),'oxygen_delta':round(self.oxygen-before[1],1),
            'route_before':before[2],'route_after':len(self.route())-1,'bridge':self.bridge,'effect':effect}
        self.log('Round {}'.format(self.round), effect + ' Route recalculated.')
        self.round += 1
        self.votes = {}
        self.round_left += self.ROUND_SECONDS
        self.check_outcome()

    def check_outcome(self):
        if self.battery <= 0 or self.oxygen <= 0:
            self.status = 'lost'
            self.log('Control', 'Mission lost: '+('battery depleted.' if self.battery <= 0 else 'oxygen expired.'))
        elif self.carrying and self.position == SHELTER:
            self.status = 'won'
            self.log('Control', 'Crew delivered safely. Mission complete!')

    def advance(self, seconds):
        # Event boundaries make results independent of HTTP polling frequency.
        while seconds > 1e-9 and self.status == 'running':
            dt = min(seconds, self.round_left, self.move_left, max(0, self.oxygen))
            self.oxygen -= dt
            self.elapsed += dt
            self.round_left -= dt
            self.move_left -= dt
            seconds -= dt
            self.check_outcome()
            if self.status != 'running':
                break
            if self.round_left <= 1e-9:
                self.resolve_round()
            if self.status == 'running' and self.move_left <= 1e-9:
                route = self.route()
                if len(route) > 1:
                    self.position = route[1]
                    self.battery -= 2.6
                    if self.position == CREW and not self.carrying:
                        self.carrying = True
                        self.log('Control', 'Crew aboard! Deliver them to the shelter in the southeast.')
                self.move_left += self.STEP_SECONDS
                self.check_outcome()

    def tick(self):
        now = self.clock()
        self.advance(max(0, now-self.last))
        self.last = now

    def snapshot(self):
        return {'status': self.status, 'position': self.position, 'carrying': self.carrying,
                'battery': round(max(0,self.battery),1), 'oxygen': round(max(0,self.oxygen),1),
                'elapsed': round(self.elapsed,1), 'bridge': self.bridge, 'blocked': sorted(self.blocked),
                'route': self.route(), 'roads': sorted(ROADS), 'round': self.round, 'token': self.token,
                'last_decision':self.last_decision,'round_seconds':self.ROUND_SECONDS,
                'round_left': round(max(0,self.round_left),2), 'options': OPTIONS,
                'counts': {o['id']: list(self.votes.values()).count(o['id']) for o in OPTIONS},
                'events': self.events, 'mode': 'SIMULATED CHAT — Twitch disconnected'}
