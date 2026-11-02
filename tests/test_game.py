import unittest
from game import Game, shortest_path, ROADS, BASE, CREW, SHELTER
from twitch_adapter import TwitchAdapter

class PathTests(unittest.TestCase):
    def test_shortest_route_and_adjacency(self):
        path = shortest_path(BASE, CREW)
        self.assertEqual(len(path)-1, 14)
        self.assertEqual((path[0], path[-1]), (BASE, CREW))
        for a,b in zip(path,path[1:]):
            self.assertEqual(abs(a[0]-b[0])+abs(a[1]-b[1]),1)
            self.assertIn(b, ROADS)

    def test_closed_bridges_and_unreachable(self):
        path = shortest_path(BASE, CREW, {(7,2),(7,4)})
        self.assertIn((7,6), path)
        self.assertNotIn((7,2), path)
        self.assertEqual(shortest_path(BASE, CREW, {(7,2),(7,4),(7,6)}), [])
        self.assertEqual(shortest_path((0,0), CREW), [])
        self.assertEqual(shortest_path(BASE, BASE), [BASE])

class MissionTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(clock=lambda: 0)
        self.game.start()

    def vote(self, option, viewer='alice'):
        return self.game.vote(viewer, option, self.game.token)

    def test_duplicate_casefold_and_new_round(self):
        self.assertTrue(self.vote('supply')[0])
        self.assertFalse(self.vote('north',' ALICE ')[0])
        token = self.game.token
        self.game.advance(7)
        self.assertFalse(self.game.vote('bob','north',token)[0])
        self.assertTrue(self.vote('north')[0])

    def test_tie_order_and_no_votes(self):
        self.vote('scan','a')
        self.vote('supply','b')
        self.game.advance(7)
        self.assertEqual(self.game.bridge,4)
        self.game.advance(7)
        self.assertEqual(self.game.bridge,2)

    def test_vote_effects(self):
        for option, bridge, battery, oxygen in [('north',2,42,65),('scan',4,38,73),('supply',6,64,59)]:
            game = Game(clock=lambda:0)
            game.start()
            game.vote('a',option,game.token)
            game.resolve_round()
            self.assertEqual((game.bridge,game.battery,game.oxygen),(bridge,battery,oxygen))
            self.assertIn((7,bridge), game.route())

    def test_win_with_supply_and_delivery(self):
        self.vote('supply')
        self.game.advance(60)
        self.assertEqual(self.game.status,'won')
        self.assertTrue(self.game.carrying)
        self.assertEqual(self.game.position,SHELTER)
        self.assertGreater(self.game.battery,0)

    def test_loss_without_supply(self):
        self.game.advance(60)
        self.assertEqual(self.game.status,'lost')
        self.assertLessEqual(self.game.battery,0)

    def test_oxygen_loss_before_arrival(self):
        self.game.oxygen = .5
        self.game.advance(20)
        self.assertEqual(self.game.status,'lost')
        self.assertEqual(self.game.position,BASE)
        self.assertEqual(self.game.elapsed,.5)

    def test_restart_clears_state_and_rejects_old_token(self):
        old = self.game.token
        self.vote('scan')
        self.game.advance(8)
        self.game.restart()
        self.assertEqual(self.game.status,'ready')
        self.assertEqual(self.game.position,BASE)
        self.assertFalse(self.game.carrying)
        self.assertEqual(self.game.votes,{})
        self.assertEqual((self.game.battery,self.game.oxygen,self.game.round),(42,65,1))
        self.assertNotEqual(old,self.game.token)
        self.game.start()
        self.assertFalse(self.game.vote('b','north',old)[0])

    def test_poll_frequency_independence(self):
        a,b = Game(clock=lambda:0),Game(clock=lambda:0)
        for game in (a,b):
            game.start()
            game.vote('a','supply',game.token)
        a.advance(35)
        for _ in range(350):
            b.advance(.1)
        self.assertEqual(a.snapshot(),b.snapshot())

    def test_invalid_votes_and_adapter(self):
        for viewer, option in [(None,'north'),('', 'north'),('x'*41,'north'),('a','invalid')]:
            self.assertFalse(self.vote(option,viewer)[0])
        adapter = TwitchAdapter(self.game)
        self.assertFalse(adapter.connected)
        self.assertFalse(adapter.accept_chat('1','hello')[0])
        self.assertTrue(adapter.accept_chat('1','!supply')[0])
        self.assertFalse(adapter.accept_chat('1','!north')[0])

if __name__ == '__main__':
    unittest.main()
