"""Notification validation boundary: no direct browser endpoint or network access.

A future trusted EventSub transport must call accept_notification under server.LOCK,
with the game round token captured at ingress under that same lock. Never retag a
queued event with a newer token. Verified API IDs must configure the subscription;
browser names/IDs and untrusted HTTP payloads must never enter this boundary.
"""
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import re
import time
from typing import Protocol


_RFC3339 = re.compile(
    r'(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})[Tt]'
    r'(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})'
    r'(?:\.(?P<fraction>[0-9]{1,43}))?'
    r'(?P<zone>[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])')
_EPOCH = datetime(1970,1,1,tzinfo=timezone.utc)


def _parse_rfc3339_timestamp(value):
    """Strict bounded provider timestamp; normalize fractions for Python 3.9.

    RFC3339 permits T/Z in either case and explicit HH:MM offsets. Retain the
    complete fraction for freshness checks even when datetime truncates to 6
    digits. Calendar/time values (including unrepresentable leap seconds) fail
    closed through datetime validation. No permissive ISO-only forms are accepted.
    """
    if not isinstance(value,str) or len(value) > 64:
        raise ValueError('Invalid RFC3339 timestamp.')
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ValueError('Invalid RFC3339 timestamp.')
    fraction = match['fraction'] or '0'
    normalized = match['date']+'T'+match['time']
    if match['fraction'] is not None:
        normalized += '.'+fraction[:6].ljust(6,'0')
    normalized += '+00:00' if match['zone'] in ('Z','z') else match['zone']
    try:
        return datetime.fromisoformat(normalized), fraction
    except ValueError:
        raise ValueError('Invalid RFC3339 timestamp.') from None


def valid_user_id(value):
    return isinstance(value, str) and 1 <= len(value) <= 32 and value.isascii() and value.isdecimal()


def valid_message_id(value):
    return isinstance(value, str) and 1 <= len(value) <= 128 and not any(ord(c) < 33 for c in value)


class VoteTarget(Protocol):
    @property
    def token(self) -> str: ...
    def vote(self, viewer: str, option: str, token: str): ...


class TwitchAdapter:
    connected = False  # Always disconnected: this module cannot establish a connection.

    def __init__(self, game: VoteTarget, broadcaster_id=None, user_id=None,
                 clock=time.time, max_seen=512, max_age=30):
        if broadcaster_id is not None and not valid_user_id(broadcaster_id):
            raise ValueError('Expected verified numeric broadcaster ID')
        if user_id is not None and not valid_user_id(user_id):
            raise ValueError('Expected verified numeric subscription user ID')
        if not isinstance(max_seen, int) or not 1 <= max_seen <= 10000:
            raise ValueError('Invalid dedup capacity')
        if not isinstance(max_age, (int, float)) or not 0 < max_age <= 120:
            raise ValueError('Invalid freshness window')
        self.last_receipt = None
        self.source = 'simulated'
        self.game, self.broadcaster_id, self.user_id = game, broadcaster_id, user_id
        self.clock, self.max_seen, self.max_age = clock, max_seen, max_age
        self._seen = deque()
        self._notification_ids, self._chat_ids = set(), set()

    def accept_chat(self, viewer_id: str, text: str, token=None):
        """Trusted offline command mapper retained for existing tests; not a live API."""
        if not valid_user_id(viewer_id) or not isinstance(text, str) or len(text) > 2000:
            return False, 'Invalid chat shape.'
        option = {'!north': 'north', '!scan': 'scan', '!supply': 'supply'}.get(text.strip().lower())
        if option is None:
            return False, 'Not a mission command.'
        return self.game.vote('twitch:'+viewer_id, option, self.game.token if token is None else token, source=self.source)

    def accept_notification(self, envelope, received_token):
        """Validate a decoded channel.chat.message v1 notification, then cast a vote.

        Freshness (30s past, 5s future by default) and bounded dedup are local
        defensive policies, not claims about Twitch delivery guarantees. Keep this
        adapter across mission restarts; dedup is transport-lifetime state.
        """
        self.last_receipt = None
        reject = (False, 'Rejected offline notification.')
        if not self.broadcaster_id or not self.user_id or not isinstance(envelope, dict):
            return reject
        metadata, payload = envelope.get('metadata'), envelope.get('payload')
        if not isinstance(metadata, dict) or not isinstance(payload, dict):
            return reject
        if (metadata.get('message_type') != 'notification' or
                metadata.get('subscription_type') != 'channel.chat.message' or
                metadata.get('subscription_version') != '1'):
            return reject
        subscription, event = payload.get('subscription'), payload.get('event')
        if not isinstance(subscription, dict) or not isinstance(event, dict):
            return reject
        condition = subscription.get('condition')
        if (subscription.get('type') != 'channel.chat.message' or subscription.get('version') != '1' or
                not isinstance(condition, dict) or
                condition.get('broadcaster_user_id') != self.broadcaster_id or
                condition.get('user_id') != self.user_id or
                event.get('broadcaster_user_id') != self.broadcaster_id):
            return reject
        notification_id, chat_id = metadata.get('message_id'), event.get('message_id')
        message = event.get('message')
        if (not valid_message_id(notification_id) or not valid_message_id(chat_id) or
                not valid_user_id(event.get('chatter_user_id')) or not isinstance(message, dict) or
                not isinstance(message.get('text'), str) or len(message['text']) > 2000):
            return reject
        timestamp = metadata.get('message_timestamp')
        try:
            stamp,fraction = _parse_rfc3339_timestamp(timestamp)
            whole = stamp.astimezone(timezone.utc).replace(microsecond=0) - _EPOCH
            # Avoid float epoch rounding or truncation admitting a timestamp just
            # outside the existing -5s/+max_age bounds. 80 digits covers the
            # complete bounded fraction plus supported calendar/clock precision.
            with localcontext() as context:
                context.prec = 80
                event_time = Decimal(whole.days*86400+whole.seconds)+Decimal('0.'+fraction)
                age = Decimal(self.clock())-event_time
                if not age.is_finite() or not Decimal(-5) <= age <= Decimal(self.max_age):
                    return reject
        except (ValueError, OverflowError):
            return reject
        action = {'!north':'north','!scan':'scan','!supply':'supply'}.get(message['text'].strip().lower())
        self.last_receipt = {'action':action,'outcome':'rejected',
            'round':getattr(self.game,'round',None),'mission':getattr(self.game,'epoch',None)}
        if notification_id in self._notification_ids or chat_id in self._chat_ids:
            self.last_receipt['outcome'] = 'duplicate'
            return False, 'Duplicate notification.'
        self._seen.append((notification_id, chat_id))
        self._notification_ids.add(notification_id)
        self._chat_ids.add(chat_id)
        if len(self._seen) > self.max_seen:
            old_notification, old_chat = self._seen.popleft()
            self._notification_ids.remove(old_notification)
            self._chat_ids.remove(old_chat)
        if not isinstance(received_token, str) or received_token != self.game.token:
            self.last_receipt['outcome'] = 'stale_round'
            return False, 'Notification belongs to a closed round.'
        ok,reason = self.accept_chat(event['chatter_user_id'], message['text'], received_token)
        self.last_receipt['outcome'] = ('accepted' if ok else 'not_command' if action is None else
            'not_running' if getattr(self.game,'status',None) != 'running' else
            'already_voted' if reason == 'One vote per viewer per round.' else 'rejected')
        return ok,reason
