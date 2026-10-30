# 数据与离线交付

## 项目目录

```text
项目目录/
  project_meta.json
  coverage.json
  orders.json
  orders.js
  story.json
  index.html
  styles.css
  app.js
  images/
  exports/
```

采集阶段无需已有网页。cache/和progress.json可保存扫描状态，不放凭据。真实订单原入口为外链，需要网络与登录；本地图片、CSS和JS必须可离线读取。

## 数据约定

- `project_meta.json`：`schema_version:1`、`platform:"taobao"`、`title`（用户标题，非空字符串，默认“消费手账”）、`mode:"full"`（若用户明确缩小/抽样可用selected）、`timezone:"Asia/Shanghai"`、`requested_range:{start,end}`（YYYY-MM-DD）。可加actual_range、plan_year、run_status、金额口径说明。full是目标，是否读齐由覆盖报告证明。
- `coverage.json`：数组，每项year、status、scanned_count、saved_count、note；status为complete/partial/selected/unread/failed/empty。计数未知用null，确实完整读取且无订单才empty。
- `orders.json`：父订单数组。每项`order_id`字符串、`placed_at`带时区ISO时间、`raw_status`、`is_success:true`、`currency`、`paid_amount`十进制字符串或null、`refund_amount`十进制字符串或null、`amount_basis`（original_paid/net_after_refund/unknown）、`url`原入口、`items`非空数组。
- item字段：`item_id`字符串、`name`、`spec`或null、`quantity`正整数、`image_path`项目内路径或null、`image_status`（saved/failed/unavailable）。平台无行ID时用订单内稳定序号并注明来源，不伪造平台ID。
- 多商品父订单只计一次实付。paid_amount与refund_amount原值保留；计算净支出前核清amount_basis。unknown不算净额，net_after_refund不再扣退款，未知金额不填0。按币种汇总，不凭商品标价填订单实付。
- `orders.js`：与JSON同源的普通JS数据，如`window.CONSUMPTION_JOURNAL_DATA = {...};`；JSON.stringify后把`<`替为`\u003c`。不得夹带Cookie/令牌或未清洗HTML，不把用户内容执行为脚本。
- `story.json`：`overview:{text,source_ids}`、`themes:[{id,title,text,source_ids,image_paths,layout}]`。source_ids指真实父order_id；若主题具体到商品另加item_ids，可回查父订单。布局A/B/C不展示到UI；没有人物、角色或影视彩蛋字段。

## 离线与计划

新建item增加图片`origin`：`platform`或`user_provided`。前者保存对应平台`source_url`，核对商品和规格；后者保存`provided_reference`（授权实拍文件说明）。缺图仍如实标记，不用AI/卡通/相似商品替代。装饰单独放decorations/，不能作为item.image_path或主题证据image_paths。旧数据缺来源标记时补核验，不能只凭路径通过就认定图片真实。

日历按下单北京时间索引，搜索/品类筛选遍历全部已收录订单；无订单、未读取、失败不混同。数量要区分父订单与商品件数，不由有限资料外推总消费。

普通script加载orders.js，不依赖file:// fetch JSON、CDN字体/脚本或运行时AI。localStorage保存位置和计划，需实测file://兼容；JSON导出/导入作可携带备份。导入前可下载当前备份，按ID合并，冲突保留手动版本，有恢复入口，不清空原记录。

隐私默认：分享图隐藏账号、订单号、精确金额、私人照片；整个离线包也不公开部署。参考案例图片只存在Skill里，不复制成用户订单。

## 本地检查

`python scripts/check_project.py 项目目录 --kind taobao --stage data`

完成网页后改`--stage final`。检查父ID、金额格式、数量、成功状态、时间、图片路径、story来源和离线入口。失败退出非零；仅本地标准库，不联网。`python scripts/test_check_project.py`用合成夹具回归，不登录、不读取真实账户。

检查通过不证明页面金额与淘宝一致、是否全量、消费结论正确或视觉/交互可用；仍按验收参考人工和浏览器实测。
