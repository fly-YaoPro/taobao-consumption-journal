# 京东采集分支

本分支只替换平台入口和订单规范化；隐私筛选、真实图、分析、纸页回看、订单日历、可编辑计划及分享验收全部沿用原流程。完整任务仍默认由Agent采集，不要求用户先爬好资料。

## 正常入口与范围

- 由用户登录京东并处理验证码。从官网“我的订单”进入当前实际页面；2026-11-09小样本观察到正常入口跳转 `https://order.jd.hk/center/list.action`，适配器也接受 `order.jd.com/center/list.action`。这是允许读取的订单页范围，不是让Agent猜接口、读取Cookie或绕过登录。
- 必须核验当前账号与筛选。现场默认“近3个月”，年份下拉可见“今年内”、2025年至2014年；这是当次UI观察，不是所有账号或未来页面的固定保证。按任务日期和实际下拉选项选择相交的年份窗口，本地再按requested_range精确过滤。
- 一个项目只处理京东，`project_meta.platform`必须显式为`"jd"`，用户范围不变；规范批次和每条订单也带 `platform:"jd"`。不要改淘宝项目的标签继续跑，不能合并同号的跨平台记录。
- 首屏先保存，正常逐屏滚动让本页商品图懒加载；反复读取首屏未加载的img或随便等待，不等于已读全页。窗口/页码推进后重新做该页正常滚动，再保存稳定列表。不操作购买、退款、确认收货、删除或评价按钮。

## 数据、状态与拆单

`jd_adapter.py`只读当前正常列表DOM；`collect_jd.py`负责平台、年份窗口、页码、双快照和断点。宿主不允许脚本读取DOM时，改用其正常可见页面读取能力，不新开无登录态浏览器、不私接CDP绕过限制。由宿主正常UI完成滚动、年份选择及翻页，不把JS提取器改成点击器。

- **状态**：只纳入精确“已完成”；等待收货、等待付款、取消、关闭和未知状态都不算已完成，保留实际原状态。不要为了补量手动改成成功。
- **身份**：订单号与商品ID保持字符串；商品数量必须来自实际显示，未知不默认为1。秒级下单时间按北京时间保存为带时区ISO，保留原时间；同SKU不同规格或多行不错误合并。
- **拆单**：每个实际子订单卡片保存一条，`parent_order_id`仅记现场实际读到的父号。父拆单banner总额不作为额外消费，也不复制到子卡片。页首拆单没有banner时保持父号null、`split_relation_uncertain:true`；不能把前页父号、相邻商家或相同金额当关系依据。不将子单数量等同支付次数。
- **金额**：当次列表价格没有明确“实付”标签，适配器只存`observed_amount`和`observed_amount_label`；paid/refund保持null、basis为unknown，不把观察值换名叫实付或净支出。需要精确金额结论时，按用户权限从正常详情核对标签与退款后补字段；否则从已核验商品和时间做回看，不硬算花费。
- **入口**：保留真实观察到的列表/详情URL。未打开详情就不根据订单号拼造详情地址；来源能如实返回已读取列表，不承诺一定直达某单详情。

## 批次、窗口和续跑

仅当当前宿主允许相应只读DOM协议时，接入以下接口；`bu.js`为宿主实际提供的页面读取能力。Agent先在Skill目录外准备明确platform与完整requested_range的元数据，并根据实际年份入口生成无缺口、不重叠的periods；每项含label/start/end。标签采用实际核验值，如“今年内订单”或“2025年订单”，不能用“近3个月”代替年度计划，也不能把脚本示例的年份当固定业务范围。

```python
from collect_jd import configure_browser, collect_browser

def select_period(bu, label):
    # 接入宿主已核验的正常年份下拉操作；不使用JS点击或猜URL。
    host_normal_select_year(bu, label)

def advance_page(bu, target_page):
    # 正常点击下一页；采集器另核对实际活动页码与订单集合变化。
    host_normal_next_page(bu)

def prepare_page(bu):
    # 正常逐屏滚动整页并等待图片加载，不以JS强改src或注入滚动。
    host_normal_scroll_entire_list(bu)

def verify_empty_period(bu, period):
    # 正常UI实查当前年份、加载已结束且确实无订单，不能只凭一行空态文案。
    # 必须返回实际核验结果：verified严格为True、label为实际核对的年份标签、
    # note为非空核验文字；无法确认就返回verified=False，不编造结论。
    return host_normal_verify_empty_year(bu, period)

print(configure_browser(bu, source, account_key='已核验账号的本地别名',
      periods=periods, select_period=select_period, prepare_page=prepare_page,
      verify_empty_period=verify_empty_period))
print(collect_browser(bu, source, select_period, advance_page,
      prepare_page=prepare_page, verify_empty_period=verify_empty_period,
      max_pages=1, deadline_seconds=20))
# 核对页码、年份、全页图源与落盘后，再用默认5页/45秒批次。
```

上例的 `host_normal_*` 是接入当前宿主工具的回调占位，不是包内命令或要求安装的固定MCP；由Agent实现，不让用户手工填脚本。`verify_empty_period`仅在确定不会遇到空年度时可省，**所有空年度都必须实查回调，包括已识别“没有相关订单哦”的正常空态**。返回值须为严格的 `{"verified":True,"label":period["label"],"note":"实际正常页面核实结论"}`；其中label和note来自真实核查，不能机械照填此示例。缺回调、标签不匹配或无非空文字说明均handoff，不记empty/complete。回调后采集器再读当前页面；若标签变动、出现订单或仍在loading就停止重核，防止把上一年残留空态当本年为空。`jd_lazy_images_pending_normal_scroll_and_reobserve`表示仍有图源等待正常滚动加载，先补正常滚动再重读，不把占位源强记成功。

按 [稳定分批采集](collection-fast-path.md) 的有界预算执行，默认5页/45秒、上限10页/120秒，新页至少留4秒冷却，同一目录单写入者。每个游标必须能区分年份窗口与页码；同一页号换年份不是同一页。第一页与下一页都核对活动页码、年份和订单集合变化，不能页码先变、列表未更新就提交。

每个窗口正常确认终点后才切换下一个请求年份。`complete`只说明本次已核验窗口/可访问列表的结束，不自动证明近十年齐全；每年的coverage分别记录complete/partial/unread/failed/empty。只有完整读过且确实为空才empty；没有相关订单的2016年不代表其他年份也没有。

状态、规范页缓存与订单保存平台/账号别名/日期范围，不保存整页DOM、凭据、地址或聊天。平台/账号/窗口与断点不符时停止，先核对或使用独立新项目，不能覆盖旧订单。登录失效、验证、风控、重复页、未知结构、年份或页码不推进都保存已得进度后暂停，不无限重试。

## 图片到页面

本页真实商品图源应在正常滚动后获取；不要把懒加载占位、整页营销图或任意相似图片当商品图。待批次订单落盘后，核验实际观察到的图片主机，再用`manage_media.py`排队下载全部源图；不只下载首页几张，不与采集同时改orders.json。

```bash
python scripts/manage_media.py "京东资料目录" plan --allow-host 实际观察并核验的图片主机
python scripts/manage_media.py "京东资料目录" download --workers 3 --max-mb 512 --max-file-mb 25
python scripts/check_project.py "京东资料目录" --kind jd --stage data
```

不猜京东高清规格、不去掉签名/路径后缀凑高清；如本图不够清晰，从对应同商品同规格的正常页面补图。HTTP成功不等于图片成功，核验文件格式、尺寸和真实内容。营销文字很多的真实图可留原图入口，但不冒充干净摄影放大；逐图分类、必要裁切保留实物事实，不补画商品。仍须走完item.image_path、story.visuals、板块选图、构建复制、浏览器实际加载与分享导出的完整链路。

```bash
python scripts/build_journal.py --source "京东资料目录" --output "新的京东手帐目录" --skin collage
# 页面实际下载1080×1440分享PNG，存入生成目录exports/后再验收
python scripts/check_project.py "新的京东手帐目录" --kind jd --stage final
```

私密订单先整单排除，再生成叙事和计划；原始资料不进网页包。上线必须另获用户明确确认，不因新增京东默认上传数据。

## 本次验证边界

截至2026-11-09，现场只做小样本正常页面验证：近3个月第一页20条、正常下一页4条且下一页禁用；2016年显示没有相关订单。切换2025年第一页后，包内正式 `LIST_PAGE_SCRIPT` 在实页读到20个订单卡片，其中16个精确“已完成”，共24个商品行；日期与2025窗口一致。该页正常逐屏滚动前为11个有效图源、13个懒加载待完成，滚动后为24个有效图源、0个待完成；这验证了不能只读首屏就宣布缺图。另下载并实际查看2张500×500 JPEG，均为带较多营销字的真实平台商品图，可回查原图，但不据此当干净摄影使用。

离线合成回归已验证京东规范数据经真实starter构建、有效本地图加载、日历/类别、自动计划/编辑保存和实际分享PNG导出，final返回ok。**尚未完成真实账号近十年全量采集、全部图片下载或完整回看产物的端到端验收**；合成通过不替代这些结果。正式运行仍逐项核对账号、当时UI、年份覆盖、状态、金额、图片和交互，最终只报告实际完成范围。
