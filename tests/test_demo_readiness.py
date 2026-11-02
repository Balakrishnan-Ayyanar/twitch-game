"""Fake notifications only. No provider, sockets, existing storage or user messages."""
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from game import Game
from oauth import TokenSnapshot
from eventsub import EventSubTransport
import test_eventsub as fixtures
from tools.check_source import scan, SOURCES

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now=[100.]
        self.game=Game(clock=lambda:0)
        self.socket=fixtures.FakeSocket([fixtures.welcome()])
        self.token=TokenSnapshot('FAKE_PRIVATE_TOKEN','fake-client','101',1000)
        self.worker=EventSubTransport(self.game,threading.RLock(),lambda:self.token,approved=True,
            socket_factory=fixtures.FakeSockets([self.socket]),helix=fixtures.FakeHelix(),
            clock=lambda:self.now[0],wall_clock=lambda:fixtures.NOW)
        self.worker.start(('fake','origin'),threaded=False)
        self.worker.step()

    def send(self,message):
        self.socket.items.append(json.dumps(message));self.worker.step()

    def test_ack_is_not_delivery_and_ready_command_is_not_accepted_vote(self):
        status=self.worker.status()
        self.assertEqual((status['subscription_acks'],status['validated_notifications'],status['accepted_votes']),(1,0,0))
        self.send(fixtures.notification())
        status=self.worker.status()
        self.assertEqual((status['validated_notifications'],status['accepted_votes']),(1,0))
        self.assertEqual(status['receipts'][-1]['outcome'],'not_running')
        self.game.start()
        self.send(fixtures.notification('n2','c2'))
        status=self.worker.status()
        self.assertEqual((status['validated_notifications'],status['accepted_votes']),(2,1))
        self.assertEqual(status['receipts'][-1]['outcome'],'accepted')
        self.assertEqual(self.game.votes,{'twitch:303':'supply'})
        self.assertEqual(self.game.events[-1]['who'],'Twitch viewer')

    def test_provider_nanoseconds_ready_receipt_running_vote_and_replay(self):
        def event(n,chat):
            result=fixtures.notification(n,chat)
            result['metadata']['message_timestamp']=datetime.fromtimestamp(fixtures.NOW,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+'.123456789Z'
            return result
        self.send(event('nano-ready','nano-chat-ready'))
        status=self.worker.status()
        self.assertEqual((status['validated_notifications'],status['accepted_votes']),(1,0))
        self.assertEqual(status['receipts'][-1]['outcome'],'not_running')
        self.game.start()
        fresh=event('nano-running','nano-chat-running')
        self.send(fresh)
        self.assertEqual(self.worker.status()['accepted_votes'],1)
        self.assertEqual(self.worker.status()['receipts'][-1]['outcome'],'accepted')
        self.assertEqual(self.game.votes,{'twitch:303':'supply'})
        self.send(fresh)
        self.send(event('nano-redelivery','nano-chat-running'))
        self.assertEqual(self.worker.status()['accepted_votes'],1)
        self.assertEqual(self.worker.status()['receipts'][-1]['outcome'],'duplicate')
        self.send(event('nano-next-message','nano-next-chat'))
        self.assertEqual(self.worker.status()['accepted_votes'],1)
        self.assertEqual(self.worker.status()['receipts'][-1]['outcome'],'already_voted')
        self.assertEqual(self.worker.status()['subscription_acks'],1)

    def test_worker_rejects_stale_future_and_malformed_nano_timestamps(self):
        base=datetime.fromtimestamp(fixtures.NOW,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        timestamps=[datetime.fromtimestamp(fixtures.NOW-31,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+'.123456789Z',
                    datetime.fromtimestamp(fixtures.NOW+6,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+'.123456789Z',
                    base+'.123456789',base+'.123456789+24:00',base+'.123456789ZZ']
        for i,timestamp in enumerate(timestamps):
            with self.subTest(timestamp=timestamp):
                event=fixtures.notification('bad-n'+str(i),'bad-c'+str(i))
                event['metadata']['message_timestamp']=timestamp
                self.send(event)
        status=self.worker.status()
        self.assertEqual((status['validated_notifications'],status['accepted_votes']),(0,0))
        self.assertEqual(status['receipts'],[])
        self.assertTrue(status['connected'])

    def test_invalid_crosschannel_does_not_count_and_noncommand_is_redacted(self):
        wrong=fixtures.notification();wrong['payload']['event']['broadcaster_user_id']='999'
        self.send(wrong)
        self.assertEqual(self.worker.status()['validated_notifications'],0)
        self.send(fixtures.notification('n2','c2',text='PRIVATE_RAW_CHAT_MUST_NOT_APPEAR'))
        status=self.worker.status()
        self.assertEqual(status['validated_notifications'],1)
        self.assertEqual(status['accepted_votes'],0)
        self.assertEqual(status['receipts'][-1]['outcome'],'not_command')
        for value in ('PRIVATE_RAW_CHAT','FAKE_PRIVATE_TOKEN','display_name_is_not_identity','chat-1','chatter_user_id'):
            self.assertNotIn(value,json.dumps(status)+json.dumps(self.game.snapshot()))

    def test_duplicate_restart_and_bounded_receipts(self):
        self.game.start();self.send(fixtures.notification())
        self.game.restart();self.game.start();self.send(fixtures.notification())
        self.assertEqual(self.worker.status()['accepted_votes'],1)
        self.assertEqual(self.worker.status()['receipts'][-1]['outcome'],'duplicate')
        for i in range(20):self.send(fixtures.notification('n'+str(i+10),'c'+str(i+10),text='non-command'))
        self.assertEqual(len(self.worker.status()['receipts']),12)
        self.assertEqual(self.worker.status()['accepted_votes'],1)
        self.assertIn('Current server process',self.worker.status()['receipt_scope'])

    def test_auth_expiry_status_fails_closed_without_provider_and_retry_telemetry(self):
        self.now[0]=1001
        status=self.worker.status()
        self.assertFalse(status['connected'])
        self.assertFalse(status['can_connect'])
        self.assertEqual(status['transport_status'],'authorization required')
        self.now[0]=100
        self.worker.stop();self.worker.start(('fake','origin'),threaded=False)
        # Factory has no more sockets; retry is bounded and visible.
        self.worker.step()
        status=self.worker.status()
        self.assertEqual(status['retry_count'],1)
        self.assertEqual(status['retry_in_seconds'],1)
        self.assertFalse(status['can_connect'])

class ImpactTests(unittest.TestCase):
    def test_actual_capped_delta_tie_default_and_restart(self):
        game=Game(clock=lambda:0);game.start();game.battery=99
        game.vote('a','supply',game.token);game.resolve_round()
        impact=game.snapshot()['last_decision']
        self.assertEqual(impact['battery_delta'],1)
        self.assertEqual(impact['oxygen_delta'],-6)
        self.assertEqual(impact['reason'],'most_votes')
        self.assertEqual(impact['counts'],{'north':0,'scan':0,'supply':1})
        self.assertEqual(impact['route_after'],len(game.route())-1)
        game.resolve_round();self.assertEqual(game.last_decision['reason'],'no_votes')
        game.vote('a','scan',game.token);game.vote('b','supply',game.token);game.resolve_round()
        self.assertEqual(game.last_decision['reason'],'tie')
        self.assertEqual(game.last_decision['action'],'scan')
        game.restart();self.assertIsNone(game.snapshot()['last_decision'])

class SourcePlanTests(unittest.TestCase):
    def test_allowlist_excludes_all_private_and_existing_evidence(self):
        self.assertTrue(all(not name.startswith(('.twitch-local/','.venv/','evidence/','.env','.git/')) for name in SOURCES))

    def test_scanner_reports_rule_only_and_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for relative in SOURCES:
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('public placeholder')
            (root/'server.py').write_text('client_secret = "FAKE_VALUE_NOT_TO_PRINT"')
            findings=scan(root)
            self.assertEqual(findings,[('server.py',1,'literal-credential')])
            self.assertNotIn('FAKE_VALUE',repr(findings))
            (root/'server.py').unlink()
            # Only a NEW synthetic private target is used in this test.
            fake=root/'fake-private';fake.write_text('NEVER_READ')
            (root/'server.py').symlink_to(fake)
            self.assertIn(('server.py',0,'unreadable-or-unsafe-source'),scan(root))

if __name__ == '__main__':unittest.main()
