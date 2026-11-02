"""Offline fixtures only. IDs are fake; no Twitch requests, tokens or sockets."""
import copy
from datetime import datetime, timezone, timedelta
import unittest
from game import Game
from twitch_adapter import TwitchAdapter, _parse_rfc3339_timestamp

NOW = 1800000000

def notification(n='notification-1', chat='chat-1', chatter='303', text='!supply', age=0):
    return {'metadata': {'message_id': n, 'message_type': 'notification',
            'message_timestamp': datetime.fromtimestamp(NOW-age,timezone.utc).isoformat(),
            'subscription_type': 'channel.chat.message', 'subscription_version': '1'},
            'payload': {'subscription': {'type': 'channel.chat.message', 'version': '1',
                'condition': {'broadcaster_user_id':'101','user_id':'202'}},
                'event': {'broadcaster_user_id':'101','chatter_user_id':chatter,
                    'chatter_user_login':'display_name_is_not_identity', 'message_id':chat,
                    'message':{'text':text}}}}

class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(clock=lambda:0)
        self.game.start()
        self.adapter = TwitchAdapter(self.game,'101','202',clock=lambda:NOW,max_seen=2)

    def accept(self,event,token=None):
        return self.adapter.accept_notification(event,self.game.token if token is None else token)

    def test_valid_stable_id_and_one_vote_per_round(self):
        self.assertTrue(self.accept(notification())[0])
        self.assertEqual(self.game.votes,{'twitch:303':'supply'})
        self.assertFalse(self.accept(notification('n2','c2',text='!north'))[0])
        self.game.advance(7)
        self.assertTrue(self.accept(notification('n3','c3',text='!north'))[0])
        self.assertFalse(self.adapter.connected)

    def test_duplicate_notification_and_chat_ids_across_restart(self):
        self.assertTrue(self.accept(notification())[0])
        self.game.restart()
        self.game.start()
        self.assertFalse(self.accept(notification())[0])
        self.assertFalse(self.accept(notification('new-envelope','chat-1'))[0])
        self.assertFalse(self.accept(notification('notification-1','new-chat'))[0])
        self.assertEqual(self.game.votes,{})
        self.assertTrue(self.accept(notification('n2','c2'))[0])

    def test_bound_to_ingress_round_and_mission(self):
        token = self.game.token
        self.game.advance(7)
        self.assertFalse(self.accept(notification(),token)[0])
        token = self.game.token
        self.game.restart()
        self.game.start()
        self.assertFalse(self.accept(notification('n2','c2'),token)[0])
        self.assertEqual(self.game.votes,{})
        self.assertTrue(self.accept(notification('n3','c3'))[0])

    def test_freshness_and_timestamp_shape(self):
        for age in (31,-6):
            self.assertFalse(self.accept(notification(age=age))[0])
        for stamp in ('bad','2026-01-01T12:00:00',None,{},'x'*65):
            event=notification()
            event['metadata']['message_timestamp']=stamp
            self.assertFalse(self.accept(event)[0])
        self.assertEqual(self.game.votes,{})

    def test_rfc3339_fraction_precisions_and_explicit_zones(self):
        base=datetime.fromtimestamp(NOW,timezone.utc)
        cases=[]
        for fraction in ('','1','12','123','1234','12345','123456','1234567','12345678','123456789','1234567890','0'*42+'1'):
            cases.append(base.strftime('%Y-%m-%dT%H:%M:%S')+('.'+fraction if fraction else '')+'Z')
        for offset in (timedelta(hours=5,minutes=30),-timedelta(hours=7),timedelta(hours=23,minutes=59)):
            local=base.astimezone(timezone(offset))
            text=local.isoformat()
            cases.append(text[:-6]+'.123456789'+text[-6:])
        cases.extend([base.strftime('%Y-%m-%dt%H:%M:%S')+'.123456789z',
                      base.strftime('%Y-%m-%dT%H:%M:%S')+'.123456789-00:00'])
        for i,timestamp in enumerate(cases):
            with self.subTest(timestamp=timestamp):
                event=notification('n'+str(i),'c'+str(i),chatter=str(500+i))
                event['metadata']['message_timestamp']=timestamp
                self.assertTrue(self.accept(event)[0])
                stamp,fraction=_parse_rfc3339_timestamp(timestamp)
                self.assertIsNotNone(stamp.tzinfo)
                self.assertEqual(stamp.microsecond,int(fraction[:6].ljust(6,'0')))
        stamp,fraction=_parse_rfc3339_timestamp(base.strftime('%Y-%m-%dT%H:%M:%S')+'.123456789Z')
        self.assertEqual((stamp.microsecond,fraction),(123456,'123456789'))

    def test_nanosecond_freshness_boundaries_do_not_widen_limits(self):
        cases=[(-30,'000000000',True),(-31,'999999999',False),(-30,'000000001',True),
               (5,'000000000',True),(5,'000000001',False),(6,'123456789',False)]
        for i,(offset,fraction,allowed) in enumerate(cases):
            with self.subTest(offset=offset,fraction=fraction):
                event=notification('n'+str(i),'c'+str(i),chatter=str(600+i))
                event['metadata']['message_timestamp']=datetime.fromtimestamp(NOW+offset,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+'.'+fraction+'Z'
                self.assertEqual(self.accept(event)[0],allowed)
                if not allowed:self.assertIsNone(self.adapter.last_receipt)

    def test_strict_rfc3339_rejects_malformed_naive_and_out_of_range(self):
        base=datetime.fromtimestamp(NOW,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        cases=[base,base+'.123456789',base+'Z\n',' '+base+'Z',base.replace('T',' ')+'Z',
               base+'.Z',base+',123Z',base+'.123456789ZZ',base+'+0000',base+'+00',
               base+'+00:00:00',base+'+24:00',base+'-24:00',base+'+01:60',base+'Z+00:00',
               base+'.'+'1'*44+'Z',base+'.１２３Z','2026-02-30T12:00:00.123456789Z',
               '2026-01-01T24:00:00Z','2026-01-01T23:60:00Z','2026-01-01T23:59:60Z',
               '0000-01-01T00:00:00Z',None,{},42]
        for timestamp in cases:
            with self.subTest(timestamp=timestamp):
                event=notification();event['metadata']['message_timestamp']=timestamp
                self.assertFalse(self.accept(event)[0])
                self.assertIsNone(self.adapter.last_receipt)
        self.assertEqual(self.game.votes,{})
        # Rejection does not reserve message IDs or relax other validation.
        self.assertTrue(self.accept(notification())[0])

    def test_malformed_and_cross_channel(self):
        event = notification()
        alterations = [
            ('metadata','message_type','session_welcome'),
            ('metadata','subscription_type','channel.follow'),
            ('metadata','subscription_version','2'),
            ('metadata','message_id',None),
            ('payload.subscription','type','channel.follow'),
            ('payload.subscription','version','2'),
            ('payload.subscription.condition','broadcaster_user_id','999'),
            ('payload.subscription.condition','user_id','999'),
            ('payload.event','broadcaster_user_id','999'),
            ('payload.event','chatter_user_id','browser-name'),
            ('payload.event','chatter_user_id','３'),
            ('payload.event','message_id',''),
            ('payload.event','message',{'text':[]} ),
            ('payload.event','message',{'text':'x'*2001}),
        ]
        for path,key,value in alterations:
            changed=copy.deepcopy(event)
            node=changed
            for part in path.split('.'):
                node=node[part]
            node[key]=value
            with self.subTest(path=path,key=key):
                self.assertFalse(self.accept(changed)[0])
        for malformed in (None,[],{}, {'metadata':[],'payload':{}}, {'metadata':{},'payload':None}):
            self.assertFalse(self.accept(malformed)[0])
        self.assertEqual(self.game.votes,{})
        self.assertTrue(self.accept(event)[0])  # Invalid messages did not reserve IDs.

    def test_dedup_bounded_and_not_an_unlimited_replay_store(self):
        for i in range(5):
            self.accept(notification('n'+str(i),'c'+str(i),chatter=str(400+i)))
        self.assertEqual(len(self.adapter._seen),2)
        self.assertEqual(len(self.adapter._notification_ids),2)
        self.assertEqual(len(self.adapter._chat_ids),2)
        self.assertFalse(self.accept(notification('n4','c4'))[0])
        self.assertFalse(self.accept(notification('n0','c0',age=31))[0])

    def test_no_configuration_and_non_command(self):
        self.assertFalse(TwitchAdapter(self.game).accept_notification(notification(),self.game.token)[0])
        self.assertFalse(self.accept(notification(text='hello'))[0])
        self.assertEqual(self.game.votes,{})
        for kwargs in ({'broadcaster_id':'name'},{'user_id':'name'},{'max_seen':0}):
            with self.assertRaises(ValueError):
                TwitchAdapter(self.game,**kwargs)

if __name__ == '__main__':
    unittest.main()
