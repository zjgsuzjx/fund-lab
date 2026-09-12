from pathlib import Path
from html import escape
import re
OUT=Path(__file__).parent
C={'bg':'#F4F7FC','ink':'#17243D','muted':'#64748B','blue':'#1768E8','tint':'#EAF2FF','line':'#E4EAF3','red':'#C44941','green':'#12836B','white':'#FFFFFF'}
parts=[]
def rect(x,y,w,h,fill='white',r=14,stroke=None):
    f=C.get(fill,fill);parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}"'+(f' stroke="{C.get(stroke,stroke)}"' if stroke else '')+'/>')
def text(x,y,s,size=14,color='ink',weight=400,anchor='start'):
    parts.append(f'<text x="{x}" y="{y}" font-family="Noto Sans SC, Microsoft YaHei, sans-serif" font-size="{size}" font-weight="{weight}" fill="{C.get(color,color)}" text-anchor="{anchor}">{escape(s)}</text>')
def line(x,y,x2,y2,color='line',sw=1):parts.append(f'<path d="M{x} {y} L{x2} {y2}" fill="none" stroke="{C.get(color,color)}" stroke-width="{sw}"/>')
def pill(x,y,w,s,active=False):rect(x,y,w,30,'tint' if active else 'white',15);text(x+w/2,y+20,s,12,'blue' if active else 'muted',500,'middle')
def button(y,s,secondary=False):rect(24,y,342,50,'tint' if secondary else 'blue',12);text(195,y+32,s,16,'blue' if secondary else 'white',600,'middle')
def kv(y,k,v,col='ink'):text(42,y,k,13,'muted');text(348,y,v,13,col,500,'end')
def nav(active=0):
    rect(0,844,390,76,'white',0);line(0,844,390,844)
    for i,s in enumerate(['发现基金','我的持仓','交易记录']):
        if i==active:rect(42+i*130,854,46,4,'blue',2)
        text(65+i*130,886,s,13,'blue' if i==active else 'muted',600 if i==active else 400,'middle')
    rect(135,907,120,4,'ink',2)
def start(title,sub,back=True):
    global parts
    parts=[];rect(0,0,390,920,'bg',26)
    text(24,31,'9:41',13,'ink',600);text(366,31,'模拟账户',11,'blue',500,'end')
    if back:text(24,74,'‹',30,'ink');text(52,72,title,20,'ink',700)
    else:text(24,79,title,27,'ink',700)
    text(24,108,sub,12,'muted')
def fundrow(y,name,code,kind,change):
    text(40,y,name,15,'ink',600);text(350,y,change,19,'green' if change.startswith('−') else 'red',600,'end')
    text(40,y+24,kind+' · '+code,11,'muted');text(350,y+24,'近一年涨跌幅',11,'muted',400,'end')
def finish(name):
    s='<svg xmlns="http://www.w3.org/2000/svg" width="390" height="920" viewBox="0 0 390 920">'+''.join(parts)+'</svg>'
    (OUT/(name+'.svg')).write_text(s,encoding='utf-8');return ''.join(parts)
screens=[]
start('基金练习室','用虚拟资金，练习每一个投资决定',False)
rect(24,132,342,178,'blue',20);text(44,161,'模拟总资产（元）',12,'white');text(44,207,'100,286.42',34,'white',700)
text(44,243,'累计收益',11,'white');text(346,243,'可用余额',11,'white',400,'end');text(44,270,'+286.42',19,'white',600);text(346,270,'80,000.00',19,'white',600,'end')
rect(24,330,342,46,'white',12);text(62,359,'搜索基金名称或代码',14,'muted')
icon=(OUT/'assets/search.svg').read_text();inner=re.sub(r'^.*?<svg[^>]*>|</svg>\s*$','',icon,flags=re.S);parts.append('<g transform="translate(38,344) scale(.8)" fill="none" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+inner+'</g>')
for x,w,s,a in [(24,68,'全部',True),(102,78,'债券型',False),(190,78,'指数型',False),(278,88,'混合型',False)]:pill(x,393,w,s,a)
text(24,456,'基金探索',18,'ink',700);text(366,456,'综合排序',12,'muted',400,'end')
rect(24,475,342,261);fundrow(507,'稳健纯债 A','SAMPLE001','债券型','+2.86%');line(40,547,350,547)
fundrow(580,'宽基指数 A','SAMPLE002','指数型','+8.42%');line(40,620,350,620)
fundrow(653,'均衡成长 C','SAMPLE003','混合型','−3.15%');text(40,715,'名称及表现均为设计演示数据',11,'muted')
rect(24,751,342,61,'tint',12);text(40,776,'从理解交易规则开始',14,'blue',600);text(40,796,'净值、确认时间与费用，都会影响结果。',11,'muted');nav(0)
screens.append(finish('01-discover'))
start('基金详情','演示产品 · SAMPLE001')
rect(24,132,342,205);text(42,164,'稳健纯债 A',22,'ink',700);pill(42,180,66,'债券型');pill(117,180,74,'A 类份额')
text(42,257,'+2.86%',36,'red',700);text(42,284,'近一年涨跌幅',12,'muted');line(42,298,348,298);text(42,321,'单位净值  1.0286',13);text(348,321,'09-10',12,'muted',400,'end')
rect(24,353,342,255);text(42,383,'净值走势',17,'ink',600);text(348,383,'示意曲线',10,'muted',400,'end')
for y,s in [(410,'1.030'),(455,'1.015'),(500,'1.000')]:line(82,y,348,y);text(42,y+4,s,10,'muted')
pts=[(82,496),(101,485),(119,492),(140,476),(160,480),(180,457),(198,465),(219,444),(240,451),(260,429),(282,436),(301,418),(323,424),(348,409)]
d='M'+' L'.join(f'{x} {y}' for x,y in pts);parts.append(f'<path d="{d} L348 510 L82 510 Z" fill="#EAF2FF"/><path d="{d}" fill="none" stroke="#1768E8" stroke-width="2.5" stroke-linejoin="round"/>')
text(82,529,'2025-09',10,'muted');text(348,529,'2026-09',10,'muted',400,'end')
for x,s,a in [(42,'近1月',False),(120,'近3月',False),(198,'近1年',True),(276,'成立来',False)]:pill(x,550,65,s,a)
rect(24,624,342,126);text(42,653,'交易规则',17,'ink',600);text(42,680,'示例申购费率 0.10% · 10 元起购',12);text(42,704,'交易日 15:00 前提交，按当日净值计算。',12,'muted');text(42,729,'具体确认日与费用以基金规则为准。',12,'muted')
text(24,780,'模拟练习使用演示数据，不发生真实交易。',11,'muted');button(814,'模拟买入');text(195,895,'了解规则，再做决定',11,'muted',400,'middle')
screens.append(finish('02-fund-detail'))
start('模拟买入','仅使用虚拟余额，不发生真实扣款')
rect(24,132,342,252);text(42,163,'稳健纯债 A',18,'ink',600);text(42,187,'SAMPLE001 · 债券型',11,'muted');text(42,223,'买入金额（元）',13,'muted');text(42,271,'1,000.00',38,'ink',600);line(42,287,348,287);text(42,313,'可用模拟余额 80,000.00 元',12,'muted')
for x,s in [(42,'+100'),(146,'+1,000'),(250,'+5,000')]:pill(x,330,94,s,True)
rect(24,400,342,210);text(42,432,'这笔买入如何计算',17,'ink',600);kv(466,'示例申购费率','0.10%');kv(497,'模拟申购费','1.00 元');kv(528,'净申购金额','999.00 元');kv(559,'确认净值 / 份额','待公布 / 待确认','blue');text(42,590,'费用按示例规则舍入，最终份额待确认。',11,'muted')
rect(24,626,342,123,'tint');text(42,655,'买入不会立即成交',15,'blue',600);text(42,681,'演示场景：交易日 14:30 提交。',12);text(42,704,'预计下一交易日确认，以基金规则为准。',12,'muted');text(42,728,'不会使用昨日净值或盘中估值结算。',12,'muted')
text(24,784,'此操作只影响你的模拟账户。',12,'muted');button(814,'确认模拟买入 · 1,000.00 元');text(195,895,'虚拟资金 · 可查看完整交易记录',11,'muted',400,'middle')
screens.append(finish('03-buy'))
start('买入待确认','申请已提交，等待正式净值公布')
rect(24,132,342,202,'tint',20);text(42,169,'申请已提交',22,'blue',700);text(42,217,'¥ 1,000.00',34,'ink',600);text(42,251,'稳健纯债 A · 模拟申购',13,'muted');text(42,293,'已转入买入在途，暂未计入基金持仓。',12,'blue')
rect(24,350,342,277);text(42,383,'确认进度',17,'ink',600)
for y,n,title,desc,active in [(422,'1','申请已提交','交易日 14:30 · 虚拟资金已预留',True),(496,'2','等待当日净值','公布后计算，不使用盘中估值',False),(570,'3','确认持仓份额','预计下一交易日，以基金规则为准',False)]:
    rect(42,y-18,26,26,'blue' if active else 'tint',13);text(55,y,n,12,'white' if active else 'blue',600,'middle');text(81,y,title,15,'blue' if active else 'ink',600);text(81,y+24,desc,11,'muted')
rect(24,643,342,102);kv(677,'提交后可用余额','79,000.00 元');kv(715,'买入在途','1,000.00 元','blue')
text(24,784,'确认结果更新后，会显示实际份额及费用。',11,'muted');button(814,'查看我的持仓');text(195,895,'当前状态：待确认 · 示例订单',11,'muted',400,'middle')
screens.append(finish('04-pending'))
start('我的持仓','模拟账户 · 已确认净值日期 09-10',False)
rect(24,132,342,184,'blue',20);text(42,163,'模拟总资产（元）',12,'white');text(42,207,'100,286.42',34,'white',700);text(42,248,'累计收益',11,'white');text(348,248,'持仓收益率',11,'white',400,'end');text(42,280,'+286.42',22,'white',600);text(348,280,'+1.43%',22,'white',600,'end')
rect(24,332,342,112);kv(364,'可用余额','79,000.00');kv(394,'已确认持仓','20,286.42');kv(424,'买入在途','1,000.00','blue')
rect(24,460,342,54,'tint',12);text(40,483,'1 笔买入待确认',14,'blue',600);text(40,502,'稳健纯债 A · 1,000.00 元',11,'muted');text(347,494,'查看',12,'blue',500,'end')
text(24,551,'基金持仓',18,'ink',700);text(366,551,'1 只',12,'muted',400,'end');rect(24,570,342,163);text(42,601,'稳健纯债 A',16,'ink',600);text(42,626,'SAMPLE001 · 已确认份额 19,722.36',11,'muted');line(42,641,348,641);text(42,666,'持仓金额',11,'muted');text(348,666,'持仓收益',11,'muted',400,'end');text(42,697,'20,286.42',22,'ink',600);text(348,697,'+286.42',22,'red',600,'end')
button(756,'管理持仓 / 模拟卖出',True);nav(1)
screens.append(finish('05-holdings'))
start('模拟卖出','赎回份额，金额以确认净值为准')
rect(24,132,342,213);text(42,163,'稳健纯债 A',18,'ink',600);text(42,198,'卖出份额（份）',13,'muted');text(42,245,'1,000.00',38,'ink',600);text(42,275,'可赎回 19,722.36 份 · 示例持有 45 天',11,'muted')
for x,s in [(42,'1/4'),(146,'1/2'),(250,'全部')]:pill(x,295,94,s,True)
rect(24,361,342,245);text(42,394,'预计到账试算',17,'ink',600);kv(428,'参考净值（09-10）','1.0286');kv(458,'预计赎回金额','1,028.60 元');kv(488,'示例赎回费率','0.15%');kv(518,'预计赎回费','1.54 元');line(42,535,348,535);text(42,570,'预计净到账',14,'ink',600);text(348,573,'1,027.06 元',23,'ink',600,'end')
rect(24,622,342,143,'tint');text(42,652,'确认后仍需等待到账',15,'blue',600);text(42,679,'参考净值仅用于试算，不锁定成交价。',12,'muted');text(42,703,'提交 → 净值确认 → 赎回在途 → 到账',12);text(42,727,'到账时间以基金规则为准。',12,'muted');text(42,748,'多批买入时，按各批持有期分别计算费用。',11,'muted')
text(24,790,'仅赎回模拟份额，不影响支付宝真实持仓。',11,'muted');button(814,'确认模拟卖出 · 1,000.00 份');text(195,895,'费用与到账金额均为演示试算',11,'muted',400,'middle')
screens.append(finish('06-sell'))
parts=[];rect(0,0,1450,2200,'#E8EDF5',0);text(64,76,'基金练习室',36,'ink',700);text(64,113,'用虚拟资金，练习真实的基金交易流程',18,'muted');text(1386,77,'MOBILE / V1.0',13,'blue',600,'end');text(1386,108,'演示数据 · 独立模拟产品',12,'muted',400,'end')
labels=['01  发现基金','02  查看详情','03  输入买入金额','04  等待份额确认','05  查看持仓','06  卖出前核对费用']
for i,content in enumerate(screens):
    x=64+(i%3)*466;y=184+(i//3)*1008;text(x,y-20,labels[i],16,'ink',600);parts.append(f'<g id="screen-{i+1}" transform="translate({x},{y})">{content}</g>')
text(64,2160,'设计说明：正式净值结算 / 在途资金独立展示 / 费用按持有批次计算 / 所有数据均为示例',13,'muted')
(OUT/'fund-lab-complete.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1450" height="2200" viewBox="0 0 1450 2200">'+''.join(parts)+'</svg>',encoding='utf-8')
(OUT/'preview.html').write_text('<!doctype html><meta charset="utf-8"><title>基金练习室 · 设计预览</title><style>body{margin:0;background:#E8EDF5}img{display:block;width:1450px;max-width:100%;margin:auto}</style><img src="fund-lab-complete.svg" alt="基金练习室六页设计稿">',encoding='utf-8')
print('Generated six screens and complete SVG design board.')
