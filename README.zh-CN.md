<!-- crimemaps:visual-home:start -->
<p><img src="assets/brand/police-eagle.png" width="72" height="72" alt="CrimeMaps项目标识：戴警帽的深蓝鹰"> <img src="docs/assets/city-icon.png" width="64" height="64" alt="柏林城市图标：深蓝底色上的象牙白勃兰登堡门剪影"></p>
<p><img src="assets/brand/crime-map-en.github.svg" width="320" alt="CrimeMaps Germany"> <img src="assets/brand/crime-map-de.github.svg" width="320" alt="CrimeMaps Deutschland"></p>
<p><img src="docs/assets/cityscape.jpg" width="420" alt="柏林: AI城市风光日景"> <img src="docs/assets/cityscape-night.jpg" width="420" alt="柏林: AI城市风光夜景"></p>
<p><sub>AI生成的城市日景和夜景示意图，图片不对应警方公告中的事件。</sub></p>
<!-- crimemaps:visual-home:end -->

# CrimeMaps 柏林：警方公告地图

[English](README.md) · [Deutsch](README.de.md) · [中文](README.zh-CN.md)

按月份查看已收录的柏林警方公告、公告提到的地点和周边场所。点击地图中的区域、道路或地点，可以查看对应记录与警方原文。柏林是14城地图的入口，各城市使用独立仓库和数据。

CrimeMaps还在初版阶段，公告覆盖和地点识别有局限，译文与浏览体验也需要继续改进。使用时请结合来源说明，留意可能的遗漏或错误。欢迎参与改进：指出问题、提供有依据的纠正，或贡献代码、文案和使用体验的建议。

[预定地图地址](https://ln6666.github.io/crimemaps-Berlin/)

[如何读图](#read) · [来源](#sources) · [本地运行](#run) · [更新](#updates) · [隐私与反馈](#privacy) · [国家访问分布](#stats) · [其他城市](#cities) · [许可](#license)

<a id="status"></a>

## 当前进度

新版城市地图尚未上线。此地址预留给后续发布，目前可能无法打开地图。

当前收录范围的本地地图已完成，正在准备公开版本。

状态记录日期：2026-10-03。这里说的是当前收录批次，不代表全市犯罪记录。

<a id="read"></a>

## 如何读图

选择月份，点击区域、道路或地点，查看对应公告。警方公布日期与事件发生时间分别保留，未知时间会明确说明。

六边形显示符合统计条件的公告数量，同一公告在选定月份与图层中最多计一次。一篇公告可能涉及多起事件，也可能只介绍调查、警方行动或背景情况。这里的数量不能当作犯罪总数、个人受害概率或城市安全排名。

地点按原文能够支持的精度展示。道路、线路和区域有时只能作为参照；只有行政区信息或无法定位的记录会保留在列表中，不会补造坐标。

场所颜色加深表示公告提到的附近同类场所，不表示事件发生在某一家商户内。查看附近设施或参照范围时，请结合警方原文理解。

中文与英文用于辅助阅读，警方德文原文和来源链接保留。译文可能有误，也不能提供原文没有给出的门牌或具体位置。

软件负责采集来源和整理地图。AI 可以辅助阅读和分类，其判断仍需对照原文检查。

已收录资料会核对来源、类别、地点描述和地图展示。不同AI模型对14城资料的准确程度尚未得到可比较的测量，错误和遗漏仍可能存在。

“可能仇恨犯罪”是根据原文明确偏见证据提供的AI辅助线索，不是警方认定。身份、国籍或所在街区本身不能证明犯罪动机。

<a id="sources"></a>

## 来源与覆盖范围

<!-- crimemaps:police-website:start -->
[警察官网](https://www.berlin.de/polizei/)
<!-- crimemaps:police-website:end -->

公告来源: [Polizei Berlin](https://www.berlin.de/polizei/polizeimeldungen/).

警方公开公告只是部分记录。来源没有公告、公告未收录或地点未定位，都不能理解为该区域没有案件。警察机构的辖区可能超出市界，收录时需要核实公告与本城的关系。

地点与边界资料使用 [OpenStreetMap](https://www.openstreetmap.org/copyright)，包括 [Geofabrik 区域提取包](https://download.geofabrik.de/europe/germany.html)。各条记录保留来源时间、公告编号、原文变更和地点精度。README中的插图用于识别城市，不表示案件发生位置。

<a id="run"></a>

## 本地运行

地图界面需要 Node.js 22 和 npm；来源处理工具需要 Python 3.12 与 [uv](https://docs.astral.sh/uv/)。

```sh
git clone https://github.com/LN6666/crimemaps-Berlin.git
cd crimemaps-Berlin
npm --prefix web ci
VITE_CRIMEMAPS_CITY=berlin npm --prefix web run dev
```

打开 http://127.0.0.1:5173。仓库提供代码，经过检查的地图数据另行交付，不提交到Git。没有对应城市的数据包时，界面无法显示该城记录。按城市迁移说明把已检查的数据包导入 `web/public/safety/`，不要将来源数据库或审核包复制到这个目录。

开发后端时，安装锁定依赖并运行现有本地检查：

```sh
uv sync --locked
uv run pytest test_suite/safety
```

前端生产构建命令为 `VITE_CRIMEMAPS_CITY=berlin npm --prefix web run build`。构建代码不会发布网站，也不能证明地图数据覆盖完整。

<a id="contribute"></a>

## 参与贡献

欢迎在[留言讨论](https://github.com/LN6666/crimemaps-Berlin/discussions)分享使用感受和建议，或通过[报告问题](https://github.com/LN6666/crimemaps-Berlin/issues/new/choose)反馈错误；纠错时请附上公开来源。留言需要登录 GitHub，账号和内容都会公开。请勿发布个人信息或敏感资料。这里不接收报警或紧急求助。

[提出修改](https://github.com/LN6666/crimemaps-Berlin/pulls) · [贡献说明](docs/CONTRIBUTING.zh-CN.md)

代码或文案修改请提交范围清楚的PR，见[贡献说明](docs/CONTRIBUTING.zh-CN.md)。软件问题请说明浏览器、简短复现步骤，以及相关的公开来源链接。公开Issue中不要提交个人资料、警方全文、数据库、审核包或凭据。

<a id="updates"></a>

## 更新与可靠性

新记录出现前，需要核对来源、内容、地点和浏览器显示。获取与复核需要时间，因此这里不是实时信息流。更新失败时保留上一版可用地图；各版本包含什么，以地图中的收录日期和限制说明为准。

可查看[仓库版本](https://github.com/LN6666/crimemaps-Berlin/releases)和[代码检查](https://github.com/LN6666/crimemaps-Berlin/actions)。`docs/`保留历史开发记录，历史上线描述与这里不一致时，以当前城市状态为准。

<a id="privacy"></a>

## 隐私、纠错与安全

[反馈与未知地点说明](docs/FEEDBACK.md)

底图和外部链接使用第三方服务。加载这些服务时，对方可能收到IP地址等通常连接信息。使用前请查看地图中的来源标注和隐私说明。

安全问题请查看 [SECURITY.md](SECURITY.md)。如果仓库显示“Report a vulnerability”，可使用该私密入口。不要将凭据或敏感细节写入公开Issue。

<a id="stats"></a>

## 按国家或地区统计的地图页面浏览量

<picture>
  <source media="(max-width:640px)" srcset="docs/assets/visitors-by-country.zh.mobile.svg">
  <img src="docs/assets/visitors-by-country.zh.svg" alt="尚无已公布的国家页面浏览次数：灰色世界地图和空排行" role="img" width="840">
</picture>

地图和排行显示此城市网站的 GoatCounter 国家／地区页面浏览，包括普通刷新；语言切换和地图操作不另计。这不是独立人数或 README 读者统计。小样本合并或隐藏，数值按10向下取整；灰色表示没有公布的次数，不表示零。图中标注快照日期，GitHub 图片可能有缓存。

<a id="cities"></a>

## 14城项目

柏林是默认入口。14个城市仓库现已公开，以下链接可查看各城的代码和项目说明。新地图仍待发布。

| 城市 | 仓库 |
| --- | --- |
| 柏林 | [crimemaps-Berlin](https://github.com/LN6666/crimemaps-Berlin) |
| 汉堡 | [crimemaps-Hamburg](https://github.com/LN6666/crimemaps-Hamburg) |
| 慕尼黑 | [crimemaps-Munich](https://github.com/LN6666/crimemaps-Munich) |
| 科隆 | [crimemaps-Cologne](https://github.com/LN6666/crimemaps-Cologne) |
| 法兰克福（美因河畔） | [crimemaps-Frankfurt](https://github.com/LN6666/crimemaps-Frankfurt) |
| 杜塞尔多夫 | [crimemaps-Dusseldorf](https://github.com/LN6666/crimemaps-Dusseldorf) |
| 斯图加特 | [crimemaps-Stuttgart](https://github.com/LN6666/crimemaps-Stuttgart) |
| 莱比锡 | [crimemaps-Leipzig](https://github.com/LN6666/crimemaps-Leipzig) |
| 多特蒙德 | [crimemaps-Dortmund](https://github.com/LN6666/crimemaps-Dortmund) |
| 不来梅 | [crimemaps-Bremen](https://github.com/LN6666/crimemaps-Bremen) |
| 埃森 | [crimemaps-Essen](https://github.com/LN6666/crimemaps-Essen) |
| 德累斯顿 | [crimemaps-Dresden](https://github.com/LN6666/crimemaps-Dresden) |
| 汉诺威 | [crimemaps-Hannover](https://github.com/LN6666/crimemaps-Hannover) |
| 纽伦堡 | [crimemaps-Nuremberg](https://github.com/LN6666/crimemaps-Nuremberg) |

<a id="license"></a>

## 许可与免责声明

项目代码采用 [Apache-2.0](LICENSE)。OpenStreetMap资料另受 [ODbL与署名要求](https://www.openstreetmap.org/copyright)约束。警方公告和其他来源保留各自使用条件，代码许可不等于可以任意转载这些资料。

CrimeMaps是独立项目，并非警方官方网站。判断某条记录前，请阅读对应警方原文。地图不提供紧急服务，也不衡量个人安全程度；软件按LICENSE中的条款提供。
