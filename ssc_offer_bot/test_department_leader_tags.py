# -*- coding: utf-8 -*-
"""真实事故：米娅入职确认卡在"未匹配通知名单"——运营中心新增了"AIGC原创部"
这个部门，config_common.DEPARTMENT_LEADER_TAGS里还没有对应的规则，
get_leader_tags()匹配不到，返回空名单，场景三就停止生成入职确认。

这个测试直接用config_common.py里真实的DEPARTMENT_LEADER_TAGS（不是像
test_flow.py那样另起一份自定义的测试配置），确保新加的部门规则真的生效，
以后再有类似遗漏也能第一时间在测试里发现，而不是等SSC在生产环境撞上。
"""

import ast
import os
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

# config_common.py在导入时要求这几个环境变量存在（见其顶部检查），全量测试
# 套件靠先加载test_environment_config设置好；单独运行这个文件时（不经过
# 那个加载顺序）也要能跑，所以这里也照样设置一遍，跟test_daily_sync.py
# 遇到的是同一个已知问题，setdefault不会覆盖已经设置好的真实值。
os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "test-only")
os.environ.setdefault("EXPECTED_SSC_USER_ID", "9001")

import config_common

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
ns = dict(
    unicodedata=unicodedata,
    config=NS(DEPARTMENT_LEADER_TAGS=config_common.DEPARTMENT_LEADER_TAGS),
    log=NS(warning=lambda *a, **kw: None),
)
exec(compile(ast.Module(
    body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_leader_tags'],
    type_ignores=[]), '<department_leader_tags>', 'exec'), ns)
get_leader_tags = ns['get_leader_tags']


class DepartmentLeaderTagsTests(unittest.TestCase):
    def test_aigc_original_department_under_operations_center_resolves(self):
        # 真实事故：米娅，编制组织=运营中心，入职部门=AIGC原创部。
        leaders = get_leader_tags('运营中心', 'AIGC原创部')
        self.assertEqual(leaders, ['DaBai10010', 'chuqianyiding', 'wean4790'])

    def test_existing_operations_center_departments_still_resolve(self):
        # 回归：新增规则不能影响运营中心原有几个部门的匹配结果。
        self.assertEqual(
            get_leader_tags('运营中心', '运营1部'),
            ['DaBai10010', 'chuqianyiding', 'zlei1216', 'wean4790'],
        )
        self.assertEqual(
            get_leader_tags('运营中心', 'ACFAN特战队-品牌组'),
            ['DaBai10010', 'chuqianyiding', 'zlei1216', 'wean4790'],
        )
        self.assertEqual(
            get_leader_tags('运营中心', '运营2部'),
            ['DaBai10010', 'chuqianyiding', 'xxs202215cz2025', 'wean4790'],
        )

    def test_still_unconfigured_department_returns_empty(self):
        # 运营中心下面还没配置过的部门，应该继续按现有行为返回空列表并停止
        # 发送，而不是误配到AIGC原创部或者其它部门的名单上。
        self.assertEqual(get_leader_tags('运营中心', '完全没配置过的部门'), [])


if __name__ == '__main__':
    unittest.main()
