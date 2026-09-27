# CrimeMapsBerlin

柏林警方公开公告地图：按公布月份筛选、两级六边形统计、分类 POI、50 米小型场所圆，以及可以追溯到原文的附近类型匹配。

CrimeMapsBerlin 是当前产品，替代原 CiviFlux 插件工程；不需要 Qwen、Jev、LLM、SUMO 或 QGIS。代码迁移见[PR #8](https://github.com/LN6666/CrimeMapsBerlin/pull/8)，默认分支状态以该 PR 的合并记录和 `main` 文件树为准。旧实现保留在 Git 历史，不属于当前产品。

## 运行

需要 Python 3.12、Node.js 22、[uv](https://docs.astral.sh/uv/)。

```sh
uv sync --locked
export PYTHONPATH="$PWD/src"
npm --prefix web ci
# 第一次下载约 100 MB 的柏林 OSM 提取包，校验官方 MD5
uv run python scripts/safety/fetch_osm.py
uv run python scripts/safety/extract_pbf.py
# 原文逐篇保存进度；首次补采可能需要数十分钟
uv run python -m crimemapsberlin.collector --year 2026 --full
uv run python scripts/safety/build.py
npm --prefix web run dev
```

打开 http://127.0.0.1:5173 。默认标准街道底图，可切换柏林 2026 年航空影像或本地简图；放大后按视野请求 POI。日常执行 `uv run python scripts/safety/update.py`；定时配置见 [更新维护](docs/UPDATES.md)。

## 功能和当前状态

- 六边形边长 1,100 / 275 米，年份、月份、类别筛选、点击查看公告；参考 [CrimeMapsUK 的公开方法](https://www.crimemapsuk.com/methodology/)。使用柏林 EPSG:25833 米制网格，缩放阈值 13 为本地配置，未宣称复刻未知的英国服务端参数。
- 酒吧、夜店等分别配色；小型场所半径 50 米。车站有 OSM 面则用面，无面只显示空心定位点。
- 全文定位支持德语变格、缩写、连字符、街区约束、门牌号和具名公园／车站；保留匹配依据与待核验原因。街道、地址和场所代表位置均标为近似。
- 标准地图提供街道名、建筑、水域和绿地；柏林政府航空影像按视野加载，切换时保留事件图层、月份、选中对象和相机位置。底图失败时保留本地简图；不需要 API 账号。
- 页面提供 POLIZEIKARTE 柏林及德国其他大城市的跳转链接；相关地图目录是外部参考，不作为本站定位或案件计数的数据源。
- 优先选择实际案发场景，排除逃跑、抓捕、送医和后续封路地点；保留其他案发地点候选。支持多道路路口和明确限定的案发路段，点击网格可查看路段紫色线。每篇公告仍只计一条。
- 定位 v4 区分同名行政区／小街区、车站／道路以及未具名“内院”等普通词；保留相邻句中的碰撞路口。移动列车里的袭击不能直接落在接警车站。
- 长道路及不连续道路可显示为橙色虚线候选范围，点击查看对应公报；未定位列表也可跳转到道路。保留实际片段和已有街区约束，不连接空缺、不指定案发点；这些公报仍属于未定位，不增加六边形计数或附近 POI 加深。
- 原文确定性关键词 + 空间匹配，同类型附近 POI 加深；具名场所只关联对应对象。近似位置产生的是候选关联，不是店内案发证明。
- 柏林 kbO 七个区域有官方说明和边界图链接；精确矢量边界仍待导入，页面不会伪造法定边界。
- 欧洲警方来源目录已有部分国家材料；覆盖清单明确标记未完成的国家，不能视作全欧洲穷尽检索。

警方公告是选择发布的事件，不是全量报案数据。月份是**公布月份**；没有办案结果时显示未知。没有可靠地点时保留在未定位列表，不填入“零案件”网格。自动类别识别有“未分类”出口，交通及其他公告也可以单独筛选。

## 开发与交接

```sh
uv run pytest -q
npm --prefix web run build
cd web
npx playwright install chromium
npm test
```

- [架构与数据契约](docs/ARCHITECTURE.md)
- [自动更新、失败处理与恢复](docs/UPDATES.md)
- [来源、许可和定位规则](docs/DATA.md)
- [用户要求与交接清单](docs/HANDOFF.md)

应用代码为 Apache-2.0；OSM 派生数据受 ODbL 约束。原文缓存、城市数据、生成的地图数据、账号信息均不提交 Git。公共仓库 CI 使用合成测试输入，不需要账号或付费 API。
