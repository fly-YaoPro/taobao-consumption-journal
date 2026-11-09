# 数据与离线交付

## 项目目录

```text
项目目录/
  project_meta.json
  coverage.json
  orders.json
  orders.js
  story.json
  media-report.json  构建生成的图片绑定汇总
  index.html
  styles.css
  app.js
  images/
  exports/
```

采集阶段无需已有网页。新版采集器使用collection-state.json、collection-cache/；淘宝另有browser-collection.json、collection-metrics.json，京东另有jd-browser-collection.json、jd-collection-metrics.json；图片使用media-manifest.json、media-state.json和media-download-report.json。旧cache/和progress.json不擅自删除或迁移。它们是本地运行状态，不放凭据，不随成品发布。真实订单原入口为外链，需要网络与登录；本地图片、CSS和JS必须可离线读取。

## 数据约定

- `project_meta.json`：`schema_version:1`、`platform:"taobao"`或`"jd"`、`title`（用户标题，非空字符串，默认“消费手账”）、`mode:"full"`（若用户明确缩小/抽样可用selected）、`timezone:"Asia/Shanghai"`、`requested_range:{start,end}`（YYYY-MM-DD）。平台必须明确，单个项目不能混合；京东初始化前必须已有 `platform:"jd"`，不默认当淘宝。可加actual_range、plan_year、run_status、金额口径说明。full是目标，是否读齐由覆盖报告证明。
- `coverage.json`：数组，每项year、status、scanned_count、saved_count、note；status为complete/partial/selected/unread/failed/empty。计数未知用null，确实完整读取且无订单才empty。
- `orders.json`：规范订单数组，淘宝每项为父订单，京东每项为实际子订单卡片。每项`order_id`字符串、`placed_at`带时区ISO时间、`raw_status`、`is_success:true`、`currency`、`paid_amount`十进制字符串或null、`refund_amount`十进制字符串或null、`amount_basis`（original_paid/net_after_refund/unknown）、`url`实际观察到的订单入口、`items`非空数组。新增京东行必须含 `platform:"jd"`；旧淘宝行可无platform，但显式平台不符或跨平台同号必须停止，不能覆盖或自动拼表。
- 京东拆单可含 `parent_order_id`（实际父订单号字符串或null）、`split_relation_uncertain`（严格布尔，页首拆单未读到父横幅时为true）；不凭前页、同店、金额或排列猜父号。父横幅不作为一条消费记录，不将其总额复制给子单。列表未明确实付标签时保留 `observed_amount`（十进制字符串或null）、`observed_amount_label`（原价格显示）；实付/退款仍null、basis仍unknown。只有正常详情已核实才更新paid/refund/basis，观察值不等于净支出。
- item字段：`item_id`字符串、`name`、`spec`或null、`quantity`正整数、`image_path`项目内路径或null、`image_status`（saved/failed/unavailable）。平台无行ID时用订单内稳定序号并注明来源，不伪造平台ID。采集器另记item_id_basis；日级日期另记date_precision=day，午夜仅是日期容器，不代表真实下单秒数。数量未知不默认1。图片有实际source_url时才记origin=platform；确实未取到图片及源URL时origin留空，不伪造图片来源。
- 多商品订单只计一次已核实实付，京东不重复计算拆单父横幅。paid_amount与refund_amount原值保留；计算净支出前核清amount_basis。unknown不算净额，net_after_refund不再扣退款，未知金额不填0。按币种汇总，不凭商品标价或observed_amount填订单实付。
- `orders.js`：与JSON同源的普通JS数据，如`window.CONSUMPTION_JOURNAL_DATA = {...};`；JSON.stringify后把`<`替为`\u003c`。不得夹带Cookie/令牌或未清洗HTML，不把用户内容执行为脚本。
- `story.json`：`overview:{text,source_ids}`、`themes:[{id,title,text,source_ids,image_paths,layout}]`。source_ids指本项目规范记录的真实order_id；若主题具体到商品另加item_ids，可回查对应订单。京东不引用仅存在于横幅、未纳入记录的父号。布局A/B/C不展示到UI；没有人物、角色或影视彩蛋字段。
- 展示层增加 visuals 原图映射、claim_key、home 与 arrangement，见 [素材类型](media-selection.md) 和 [实现说明](implementation.md)。原始订单标题和图片不覆盖；派生图片只供排版，放大入口仍能核对原图。计划 month 可为合法年月或空字符串，空表示暂不排期。
- 选入页面的每张图必须有visuals分类；没有映射不能静默降为source。全部确实无适合展示图片时，可写image_fallback_reason说明实际核对情况；不能用于跳过看图或隐藏普通商品图。下载响应须为真实本地图片，HTML/空文件不是saved；目录有图片但所有item.image_path为空时停止构建，先修复绑定。

## 离线与计划

页面框架使用构建器生成的 `journal-data.js` 作为运行时展示数据；`orders.json` 保存规范化的采集或导入订单。内容准备、`story.plans`、发现和图片选择字段见 [页面框架说明](implementation.md)。`orders.js` 保留同源规范数据。品类筛选读取父订单可选 `category`；Agent 按商品真实信息整理分类，保留不确定项，不据此推断职业。仅在迁移既有项目时，先导出手动计划再适配/合并，不假设跨路径 localStorage 自动共享。

新建item增加图片`origin`：`platform`或`user_provided`。前者保存对应平台`source_url`，核对商品和规格；后者保存`provided_reference`（授权实拍文件说明）。缺图仍如实标记，不用AI/卡通/相似商品替代。装饰单独放decorations/，不能作为item.image_path或主题证据image_paths。旧数据缺来源标记时补核验，不能只凭路径通过就认定图片真实。

日历按下单北京时间索引，搜索/品类筛选遍历全部已收录订单；无订单、未读取、失败不混同。数量区分规范订单、京东拆分子单/已知父关系与商品件数，不把子单数叫支付次数，也不由有限资料外推总消费。

断点还绑定平台、账号别名和日期范围。`collection_state.initialize(..., platform="jd")` 只接受明确京东元数据，规范批次和订单都带jd；原淘宝断点可兼容缺platform的旧记录，但不能把它改为京东续跑。平台冲突在缓存和订单写入前拒绝，原始文件不污染。跨平台分别建项目，计划备份也不跨项目静默合并。

普通script加载orders.js，不依赖file:// fetch JSON、CDN字体/脚本或运行时AI。localStorage保存位置和计划，需实测file://兼容；JSON导出/导入作可携带备份。导入前可下载当前备份，按ID合并，冲突保留手动版本，有恢复入口，不清空原记录。

分享图默认使用对应真实商品图，按用户要求选图；账号、地址、订单号等无关信息不进入图面。构建输出的 share_images 只保存所选本地图片的同源数据URL、短名、类型和日期，供离线canvas排版，不加入平台凭据。整个离线包不自动公开部署；示例图片不复制成用户订单。

## 本地检查

```bash
# 选择与项目meta一致的kind，不互相代替
python scripts/check_project.py 淘宝项目目录 --kind taobao --stage data
python scripts/check_project.py 京东项目目录 --kind jd --stage data
```

完成网页后改`--stage final`。检查父ID、金额格式、数量、成功状态、时间、图片路径、story来源和离线入口。失败退出非零；仅本地标准库，不联网。`python scripts/test_check_project.py`用合成夹具回归，不登录、不读取真实账户。

检查通过不证明页面金额与对应平台一致、是否全量、消费结论正确或视觉/交互可用；仍按验收参考人工和浏览器实测。京东与淘宝使用相同图片、隐私、计划和资源安全门禁；jd不是跳过原检查的轻量分支。
