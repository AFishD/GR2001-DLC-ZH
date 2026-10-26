# -*- coding: utf-8 -*-
r"""js19_codec_try.py — 用多种编码假设解码 JS19 LANG，判断哪种能出通顺中文。"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
import dlclib as L            # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
P_EN_LANG = os.path.join(REPO, 'work', 'analysis', 'js19', 'payloads',
                         '00576_EN_STRINGS.RES.bin')


def lang_entries(path=P_LANG):
    raw = open(path, 'rb').read()
    subs = L.lzo_subs(raw)
    blob = b''.join(s[0] for s in subs)
    ents, used = L.parse_lang(blob)
    return ents


def is_cjk(ch):
    return '\u4e00' <= ch <= '\u9fff'


def score_text(s):
    """汉字比例 / 常见字命中 / 乱码率。"""
    if not s:
        return 0.0, 0.0
    cjk = sum(1 for c in s if is_cjk(c))
    good = sum(1 for c in s if c in '的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞')
    common = sum(1 for c in s if c in '的一是不了人我在有他这中来上大为和国地到以说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无力它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史委乎查轻易早曾除农找装广显吧阿李标谈吃图念六引历首医局突专费号尽另周较注语仅考落青随选列武红响虽推势参希古众构房半节土投某案黑维革划敌致陈律足态护七兴派孩验责营星够章音跟志底站严巴例防族供效续施留讲型料终答紧黄绝奇察母京段依批群项故按河米围江织害斗双境客纪采举杀攻父苏密低朝友诉止细愿千值仍男钱破网热助倒育属坐帝限船脸职速刻乐否刚威毛状率甚独球般普怕弹校苦创假久错承印晚兰试股拿脑预谁益阳若哪微尼继送急血惊伤素药适波夜省初喜卫源食险待述陆习置居劳财环排福纳欢雷警获模充负云停木游龙树疑层冷洲冲射略范竟句室异激汉村哈策演简卡罪判担州静退既衣您宗积余痛检差富灵协角占配征修皮挥胜降阶审沉坚善妈刘读啊超免压银买皇养伊怀执副乱抗犯追帮宣佛岁航优怪香著田铁控税左右份穿艺背阵草脚概恶块顿敢守酒岛托央户烈洋哥索胡款靠评版宝座释景顾弟登货互付伯慢欧换闻危忙核暗姐介坏讨丽良序升监临亮露永呼味野架域沙掉括舰鱼杂误湾吉减编楚肯测败屋跑梦散温困剑渐封救贵枪缺楼县尚毫移娘朋画班智亦耳恩短掌恐遗固席松秘谢鲁遇康虑幸均销钟诗藏赶剧票损忽巨炮旧端探湖录叶春乡附吸予礼港雨呀板庭妇归睛饭额含顺输摇招婚脱补谓督毒油疗旅泽材灭逐莫笔亡鲜词圣择寻厂睡博勒烟授诺伦岸奥唐卖俄炸载洛健堂旁宫喝借君禁阴园谋宋避抓荣姑孙逃牙束跳顶玉镇雪午练迫爷篇肉嘴馆遍凡础洞卷坦牛宁纸诸训私庄祖丝翻暴森塔默握戏隐熟骨访弱蒙歌店鬼软典欲萨伙遭盘爸扩盖弄雄稳忘亿刺拥徒姆杨齐赛趣曲刀床迎冰虚玩析窗醒妻透购替塞努休虎扬途侵刑绿兄迅套贸毕唯谷轮库迹尤竞街促延震弃甲伟麻川申缓潜闪售灯针哲络抵朱埃抱鼓植纯夏忍页杰筑折郑贝尊吴秀混臣雅振染盛怒舞圆搞狂措姓残秋培迷诚宽宇猛摆梅毁伸摩盟末乃悲拍丁赵硬麦蒋操耶阻订彩抽赞魔纷沿喊违妹浪汇币丰蓝殊献桌啦瓦莱援译夺汽烧距裁偏符勇触课敬哭懂墙袭召罚侠厅拜巧侧韩冒债曼融惯享戴童犹乘挂奖绍厚纵障讯涉彻刊丈爆乌役描洗玛患妙镜唱烦签仙彼弗症仿倾牌陷鸟轰咱菜闭奋庆撤泪茶疾缘播朗杜奶季丹狗尾仪偷奔珠虫驻孔宜艾桥淡翼恨繁寒伴叹旦愈潮粮缩罢聚径恰挑袋灰捕徐珍幕映裂泰隔启尖忠累炎暂估泛荒偿横拒瑞忆孤鼻闹羊呆厉衡胞零穷舍码赫婆魂灾洪腿胆津俗辩胸晓劲贫仁偶辑邦恢赖圈摸仰润堆碰艇稍迟辆废净凶署壁御奉旋冬矿抬蛋晨伏吹鸡倍糊秦盾杯租骑乏隆诊奴摄丧污渡旗甘耐凭扎抢绪粗肩梁幻菲皆碎宙叔岩荡综爬荷悉蒂返井壮薄悄扫敏碍殖详迪矛霍允幅撒剩凯颗骂赏液番箱贴漫酸郎腰舒眉忧浮辛恋餐吓挺励辞艘键伍峰尺昨黎辈贯侦滑券崇扰宪绕趋慈乔阅汗枝拖墨胁插箭腊粉泥氏彭拔骗凤慧媒佩愤扑龄驱惜豪掩兼跃尸肃帕驶堡届欣惠册储飘桑闲惨洁踪勃宾频仇磨递邪撞拟滚奏巡颜剂绩贡疯坡瞧截燃焦殿伪柳锁逼颇昏劝呈搜勤戒驾漂饮曹朵仔柔俩孟腐幼践籍牧凉牲佳娜浓芳稿竹腹跌逻垂遵脉貌柏狱猜怜惑陶兽帐饰贷昌叙躺钢沟寄扶铺邓寿惧询汤盗肥尝匆辉奈扣廷澳嘛董迁凝慰厌脏腾幽怨鞋丢埋泉涌辖躲晋紫艰巍偷坡'.replace(' ', ''))
    garble = sum(1 for c in s if 0x80 <= ord(c) <= 0x2FFF and not is_cjk(c) and c not in '，。！？：；、（）《》“”‘’…—·【】％＋－×÷／　' and not c.isascii())
    return cjk / len(s), (good + common) / max(1, cjk) if cjk else 0.0


def try_codec(name, data, errors='replace'):
    try:
        return data.decode(name, errors)
    except Exception as e:                        # noqa: BLE001
        return '<ERR %s>' % e


def auto_scan(data):
    """JS19 cave 口径解码：<0xA1 单字节；0xA1..0xAD 双字节；>=0xAE ??? 待定。"""
    out = []
    i = 0
    while i < len(data):
        b = data[i]
        if b >= 0xA1 and b < 0xAE and i + 1 < len(data):
            out.append('P(%02X,%02X)' % (b, data[i + 1]))
            i += 2
        elif b >= 0x80:
            out.append('S(%02X)' % b)
            i += 1
        else:
            out.append(chr(b))
            i += 1
    return ''.join(out)


def main():
    ents = lang_entries()
    cjk_ents = [e for e in ents if any(b >= 0x80 for b in e.data)]
    print('total=%d high=%d' % (len(ents), len(cjk_ents)))
    tests = ['gb2312', 'gbk', 'gb18030', 'big5', 'utf-8']
    for name in tests:
        rs = []
        n_ok = 0
        for e in cjk_ents:
            s = try_codec(name, e.data)
            if s.startswith('<ERR'):
                continue
            if '\ufffd' not in s and any(is_cjk(c) for c in s):
                n_ok += 1
                rs.append(s)
        sv = [score_text(s) for s in rs]
        if rs:
            avg_cjk = sum(x[0] for x in sv) / len(sv)
            avg_good = sum(x[1] for x in sv) / len(sv)
        else:
            avg_cjk = avg_good = 0
        print('%-10s decoded_ok=%4d  avg_cjk_ratio=%.3f  avg_common=%.3f' % (name, n_ok, avg_cjk, avg_good))
        for s in rs[:3]:
            print('     %r' % s[:70])
    # cave-口径 伪解码：只统计 pair 合法性
    leads = collections.Counter()
    pair_ok = 0
    single = 0
    bad = 0
    for e in cjk_ents:
        d = e.data
        i = 0
        while i < len(d):
            b = d[i]
            if b < 0xA1:
                single += 1
                i += 1
            elif b < 0xAE:
                leads[b] += 1
                pair_ok += 1
                i += 2
            else:
                bad += 1
                i += 1
    print('cave-口径: pair=%d single=%d 高位但>=0xAE(异常单字节?)=%d' % (pair_ok, single, bad))
    print('pair lead 分布:', dict(sorted(leads.items())))


if __name__ == '__main__':
    main()
