import ast
import logging
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock


def load(config, client):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    nodes = [n for n in source.body
             if isinstance(n, ast.AsyncFunctionDef) and n.name == 'resolve_trigger_bot_id']
    ns = dict(config=config, client=client, log=logging.getLogger('test'))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), ns)
    return ns['resolve_trigger_bot_id']


def cfg(bot_id=0):
    return NS(REGULARIZATION_TRIGGER_BOT_ID=bot_id, ANNIVERSARY_TRIGGER_BOT_ID=bot_id,
              REGULARIZATION_TRIGGER_BOT_USERNAME='checker_xing_bot')


class ResolveTriggerBotTests(IsolatedAsyncioTestCase):
    async def test_username_resolved_to_id_for_both_triggers(self):
        config = cfg()
        client = NS(get_entity=AsyncMock(return_value=NS(id=777)))
        await load(config, client)()
        client.get_entity.assert_awaited_once_with('checker_xing_bot')
        self.assertEqual(config.REGULARIZATION_TRIGGER_BOT_ID, 777)
        self.assertEqual(config.ANNIVERSARY_TRIGGER_BOT_ID, 777)

    async def test_pinned_id_is_kept_without_lookup(self):
        config = cfg(bot_id=555)
        config.ANNIVERSARY_TRIGGER_BOT_ID = 0
        client = NS(get_entity=AsyncMock())
        await load(config, client)()
        client.get_entity.assert_not_awaited()
        self.assertEqual(config.ANNIVERSARY_TRIGGER_BOT_ID, 555)

    async def test_lookup_failure_keeps_zero_so_nobody_is_trusted(self):
        config = cfg()
        client = NS(get_entity=AsyncMock(side_effect=ValueError('no such user')))
        await load(config, client)()
        self.assertEqual(config.REGULARIZATION_TRIGGER_BOT_ID, 0)
        self.assertEqual(config.ANNIVERSARY_TRIGGER_BOT_ID, 0)


class XingchenGroupConfigTests(TestCase):
    def test_prod_trigger_group_is_xingchen_and_whitelisted(self):
        import importlib
        old = {k: os.environ.get(k) for k in ('BOT_ENV', 'TG_API_ID', 'TG_API_HASH')}
        os.environ.update(BOT_ENV='prod', TG_API_ID='1', TG_API_HASH='x')
        os.environ.pop('GROUP_REGULARIZATION_TRIGGER', None)
        try:
            import config
            config = importlib.reload(config)
            self.assertEqual(config.GROUP_REGULARIZATION_TRIGGER, -1004472320269)
            self.assertIn(-1004472320269, config.PRODUCTION_CHAT_IDS)
            self.assertNotIn(-1004492520637, config.PRODUCTION_CHAT_IDS)
            self.assertEqual(config.REGULARIZATION_TRIGGER_BOT_USERNAME, 'checker_xing_bot')
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
