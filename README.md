# CrimeMapsBerlin

柏林警方公开公告地图：按公布月份筛选、两级六边形统计、分类 POI、50 米小型场所圆，以及可以追溯到原文的附近类型匹配。

CrimeMapsBerlin 是当前产品，替代原 CiviFlux 插件工程；不需要 Qwen、Jev、SUMO 或 QGIS。官方来源抓取和地理计算仍是确定性程序；案件性质、事件数量和地点角色由 LLM 从全部公告原文开始逐篇识别，规则只提供候选并校验证据、来源版本和几何。结果还要交由项目所有者检查、质问和确认，才允许新地图发布。代码迁移见[PR #8](https://github.com/LN6666/CrimeMapsBerlin/pull/8)。旧实现保留在 Git 历史，不属于当前产品。

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
# 抽取候选并进入逐条复核队列；首次运行会拦截尚未复核的发布
uv run python scripts/safety/build.py
uv run python scripts/safety/review_queue.py status
npm --prefix web run dev
```

打开 http://127.0.0.1:5173 。目前公开地图只有柏林；顶部城市选择器按已确定的 14 城、三个仓库 5/5/4 顺序列出，其余城市标为“制作中”，尚无可用地图时不会跳到错误页面。默认标准街道底图，可切换柏林 2026 年航空影像或本地简图；放大后按视野请求 POI。日常执行 `uv run python scripts/safety/update.py`；定时配置和复核门禁见 [更新维护](docs/UPDATES.md)。

汉堡可独立建立**本地候选**，不会生成公开地图：

```sh
uv run python -m crimemapsberlin.hamburg --year 2026 --full
uv run python scripts/safety/fetch_osm.py --city hamburg
uv run python scripts/safety/extract_pbf.py --city hamburg
uv run python scripts/safety/build.py --city hamburg
uv run python scripts/safety/review_queue.py --city hamburg status
```

科隆和法兰克福也可用各自的 Geofabrik 区域提取包建立本地 OSM 索引，再运行
`city_candidates.py --city cologne|frankfurt`。区域文件包含目标城市以外地区，
来源范围与行政区核验仍是发布前门禁；这两个命令不会生成公开地图。

已校验正文可打包给另一个 LLM 窗口逐篇复核。命令从只读 SQLite 快照重新核对
每篇正文 SHA-256，并把正文写入本地 ZIP；默认输出到 Git 忽略的 `.runtime/`，
不能把 ZIP、正文或复核账本提交到仓库：

```sh
uv run python -m crimemapsberlin.source_review_pack \
  --city bremen \
  --db /absolute/path/to/police.sqlite \
  --channel https://www.presseportal.de/blaulicht/nr/35235
```

后续批次可以相对一个完整基线包只写入新增 `source_id`。程序会核对当前 SQLite
正文、基线包内部校验和、逐篇正文哈希、城市和来源通道，并自动校验基线 ZIP 同目录的
`.sha256`；sidecar 在其他目录时用 `--base-pack-sha256` 明确指定。基线正文有变化、
ZIP 内存在未校验文件或不安全路径时拒绝生成：

```sh
uv run python -m crimemapsberlin.source_review_pack \
  --city nuremberg \
  --db /absolute/path/to/newsroom.sqlite \
  --channel "Polizeipräsidium Mittelfranken via Presseportal newsroom 6013" \
  --base-pack /absolute/path/to/complete-baseline.zip
```

生成包只代表来源输入。每篇公告的城市范围、案件数量、全部场景以及所有者确认
仍需完成，才能进入发布流程。

慕尼黑原生站受 robots 限制，只能把已由人保存或官方提供的材料放在本机
`.runtime/safety/cities/munich/`。`munich.py --import-json` 接收一份日报 JSON，包含
`source_url`、`publisher`、`published`、`title`、`text`；若有对应 HTML、邮件、RSS/Atom
或 PDF 文件，再加相对路径 `source_file` 和该文件字节的 `source_file_sha256`。
HTML、邮件及完整 RSS 正文须包含所提供的文字；PDF 只校验文件签名和 SHA-256，
转写仍须对照原件逐字复核。程序按日报编号拆成单篇，保留来源哈希和修订号。

```sh
uv run python -m crimemapsberlin.munich \
  --import-json .runtime/safety/cities/munich/import.json
uv run python -m crimemapsberlin.munich \
  --export-review .runtime/safety/cities/munich/review-input.ndjson --review-limit 100
```

导出前会重新核对保存的正文、各编号、修订及原文件 SHA-256；导出含原文，必须留在
Git 忽略的本地目录。它只是逐篇 Codex 复核输入，`source_verified` 和
`publication_ready` 仍为 `false`，不证明历史档案完整或可发布。后续批次可用
`--review-offset` 按编号顺序分页，并为每批选择不同的本地输出文件。

仓库按已选城市顺序分为三组，名称保留产品前缀及清晰的城市序号：

| GitHub 仓库名 | 城市 | 当前状态 |
| --- | --- | --- |
| `CrimeMapsBerlin` | 柏林、汉堡、慕尼黑、科隆、法兰克福 | 现有默认入口；目前只公开柏林地图 |
| [CrimeMapsDE-Cities-06-10](https://github.com/LN6666/CrimeMapsDE-Cities-06-10) | 杜塞尔多夫、斯图加特、莱比锡、多特蒙德、不来梅 | 五城来源入口见[草稿 PR #1](https://github.com/LN6666/CrimeMapsDE-Cities-06-10/pull/1)；没有地图 |
| [CrimeMapsDE-Cities-11-14](https://github.com/LN6666/CrimeMapsDE-Cities-11-14) | 埃森、德累斯顿、汉诺威、纽伦堡 | 四城来源入口见[草稿 PR #1](https://github.com/LN6666/CrimeMapsDE-Cities-11-14/pull/1)；没有地图 |

两仓库的描述和首页列出准确城市、数据来源与未发布状态。代码及数据路径使用稳定英文小写城市 slug；已批准的派生地图数据才使用城市路径和带版本的 generation，原文、采集缓存、复核账本及未批准的候选数据不上传。

## 功能和当前状态

- 六边形边长 1,100 / 275 米，年份、月份、类别筛选、点击查看公告；参考 [CrimeMapsUK 的公开方法](https://www.crimemapsuk.com/methodology/)。使用柏林 EPSG:25833 米制网格，缩放阈值 13 为本地配置，未宣称复刻未知的英国服务端参数。
- 酒吧、夜店等分别配色；小型场所半径 50 米。车站有 OSM 面则用面，无面只显示空心定位点。
- 全文定位支持德语变格、缩写、连字符、街区约束、门牌号和具名公园／车站；保留匹配依据与待核验原因。街道、地址和场所代表位置均标为近似。
- 标准地图提供街道名、建筑、水域和绿地；柏林政府航空影像按视野加载，切换时保留事件图层、月份、选中对象和相机位置。底图失败时保留本地简图；不需要 API 账号。
- 页面提供 POLIZEIKARTE 柏林及德国其他大城市的跳转链接；相关地图目录是外部参考，不作为本站定位或案件计数的数据源。
- LLM 逐篇识别实际案发、事故、发现、搜查、抓捕、行动、背景和未知地点；一篇公告的所有有依据地点均可显示。只有一个经复核的主场景点可进入六边形，同一公告最多计一条。
- 定位 v4 区分同名行政区／小街区、车站／道路以及未具名“内院”等普通词；保留相邻句中的碰撞路口。移动列车里的袭击不能直接落在接警车站。
- 长道路及不连续道路可显示为橙色虚线候选范围，点击查看对应公报；未定位列表也可跳转到道路。保留实际片段和已有街区约束，不连接空缺、不指定案发点；这些公报仍属于未定位，不增加六边形计数或附近 POI 加深。
- LLM 提供原文语义判断，确定性空间匹配只处理已确认的地点；同类型附近 POI 加深仍需场景级原文依据，具名场所只关联对应对象。近似位置产生的是候选关联，不是店内案发证明。
- 柏林 kbO 七个区域有官方说明和边界图链接；精确矢量边界仍待导入，页面不会伪造法定边界。
- 欧洲警方来源目录已有部分国家材料；覆盖清单明确标记未完成的国家，不能视作全欧洲穷尽检索。
- 汉堡已完整抓取当前发现集的 485 篇官方新闻室正文与 OSM 道路／场所数据，并用独立米制坐标系建立本地候选。27 篇多地点公告已经逐篇拆为 105 个场景。纽伦堡已保存警方署名 Presseportal 2026 新闻室当前发现的 849/849 篇正文，并完成该新闻室的年度遍历；这不代表纽伦堡市域、巴伐利亚警方原生档案、逐篇复核或地图完成。逐篇复核和所有者批准仍阻止发布。其余城市都已有明确来源入口或因 robots 规则而关闭在线采集的离线边界；这只表示来源工程已落位，均未形成新的可发布地图。当前具体数量和障碍见[交接状态](docs/HANDOFF.md)。
- AI 复核支持“可能仇恨犯罪”等有原文依据的多标签；该标签只是线索，不等于警方最终定性。当前地图尚无经过逐条复核和所有者确认的新发布批次，也没有犯罪／仇恨风险指数；定义和边界见[数据说明](docs/DATA.md)。

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

应用代码为 Apache-2.0；OSM 派生数据受 ODbL 约束。原文缓存、城市数据、生成的地图数据、账号信息均不提交 Git。公共仓库 CI 使用合成测试输入，不需要账号或付费 API。LLM 场景决策、复核队列及结果目前只保存在本机；Codex 桌面端已安排每三天继续有界批次的逐条复核，只提交结果供所有者质询，不自动批准或发布，也未使用付费模型接口。
