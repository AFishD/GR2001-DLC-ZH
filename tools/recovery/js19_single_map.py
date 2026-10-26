# -*- coding: utf-8 -*-
r"""js19_single_map.py — 单字节高位码 → 字符 OCR（含 +2px 平移校准）。

结论（实测）：单字节字形的 FT 矩形 u0 = 8*col（漏了 +2），字实际画在 8*col+2，
故 crop 相对模板右移 2px 且右缘被裁。匹配时对模板做 dx∈[-1..4], dy∈[-2..2] 平移后取最小 xor。
"""
import json
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'dlc'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'font'))
import dlclib as L            # noqa: E402
import fontlib as F           # noqa: E402

JS = os.path.join(REPO, 'work', 'analysis', 'js19')
P_PAK = os.path.join(JS, 'payloads', '00009_COMMON.PAK.bin')
P_FT = os.path.join(JS, 'js19_ft_records.json')
P_LANG = os.path.join(JS, 'payloads', '00576_EN_STRINGS.RES.bin')
TTF = os.path.join(REPO, 'third_party', 'fonts', '方正像素16.ttf')

CW, CH = 8, 16
COMMON = (
    '的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无力它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史委乎查轻易早曾除农找装广显吧阿李标谈吃图念六引历首医局突专费号尽另周较注语仅考落青随选列武红响虽推势参希古众构房半节土投某案黑维革划敌致陈律足态护七兴派孩验责营星够章音跟志底站严巴例防族供效续施留讲型料终答紧黄绝奇察母京段依批群项故按河米围江织害斗双境客纪采举杀攻父苏密低朝友诉止细愿千值仍男钱破网热助倒育属坐帝限船脸职速刻乐否刚威毛状率甚独球般普怕弹校苦创假久错承印晚兰试股拿脑预谁益阳若哪微尼继送急血惊伤素药适波夜省初喜卫源食险待述陆习置居劳财环排福纳欢雷警获模充负云停木游龙树疑层冷洲冲射略范竟句室异激汉村哈策演简卡罪判担州静退既衣您宗积余痛检差富灵协角占配征修皮挥胜降阶审沉坚善妈刘读啊超免压银买皇养伊怀执副乱抗犯追帮宣佛岁航优怪香著田铁控税左右份穿艺背阵草脚概恶块顿敢守酒岛托央户烈洋哥索胡款靠评版宝座释景顾弟登货互付伯慢欧换闻危忙核暗姐介坏讨丽良序升监临亮露永呼味野架域沙掉括舰鱼杂误湾吉减编楚肯测败屋跑梦散温困剑渐封救贵枪缺楼县尚毫移娘朋画班智亦耳恩短掌恐遗固席松秘谢鲁遇康虑幸均销钟诗藏赶剧票损忽巨炮旧端探湖录叶春乡附吸予礼港雨呀板庭妇归睛饭额含顺输摇招婚脱补谓督毒油疗旅泽材灭逐莫笔亡鲜词圣择寻厂睡博勒烟授诺伦岸奥唐卖俄炸载洛健堂旁宫喝借君禁阴园谋宋避抓荣姑孙逃牙束跳顶玉镇雪午练迫爷篇肉嘴馆遍凡础洞卷坦牛宁纸诸训私庄祖丝翻暴森塔默握戏隐熟骨访弱蒙歌店鬼软典欲萨伙遭盘爸扩盖弄雄稳忘亿刺拥徒姆杨齐赛趣曲刀床迎冰虚玩析窗醒妻透购替塞努休虎扬途侵刑绿兄迅套贸毕唯谷轮库迹尤竞街促延震弃甲伟麻川申缓潜闪售灯针哲络抵朱埃抱鼓植纯夏忍页杰筑折郑贝尊吴秀混臣雅振染盛怒舞圆搞狂措姓残秋培迷诚宽宇猛摆梅毁伸摩盟末乃悲拍丁赵硬麦蒋操耶阻订彩抽赞魔纷沿喊违妹浪汇币丰蓝殊献桌啦瓦莱援译夺汽烧距裁偏符勇触课敬哭懂墙袭召罚侠厅拜巧侧韩冒债曼融惯享戴童犹乘挂奖绍厚纵障讯涉彻刊丈爆乌役描洗玛患妙镜唱烦签仙彼弗症仿倾牌陷鸟轰咱菜闭奋庆撤泪茶疾缘播朗杜奶季丹狗尾仪偷奔珠虫驻孔宜艾桥淡翼恨繁寒伴叹旦愈潮粮缩罢聚径恰挑袋灰捕徐珍幕映裂泰隔启尖忠累炎暂估泛荒偿横拒瑞忆孤鼻闹羊呆厉衡胞零穷舍码赫婆魂灾洪腿胆津俗辩胸晓劲贫仁偶辑邦恢赖圈摸仰润堆碰艇稍迟辆废净凶署壁御奉旋冬矿抬蛋晨伏吹鸡倍糊秦盾杯租骑乏隆诊奴摄丧污渡旗甘耐凭扎抢绪粗肩梁幻菲皆碎宙叔岩荡综爬荷悉蒂返井壮薄悄扫敏碍殖详迪矛霍允幅撒剩凯颗骂赏液番箱贴漫酸郎腰舒眉忧浮辛恋餐吓挺励辞艘键伍峰尺昨黎辈贯侦滑券崇扰宪绕趋慈乔阅汗枝拖墨胁插箭腊粉泥氏彭拔骗凤慧媒佩愤扑龄驱惜豪掩兼跃尸肃帕驶堡届欣惠册储飘桑闲惨洁踪勃宾频仇磨递邪撞拟滚奏巡颜剂绩贡疯坡瞧截燃焦殿伪柳锁逼颇昏劝呈搜勤戒驾漂饮曹朵仔柔俩孟腐幼践籍牧凉牲佳娜浓芳稿竹腹跌逻垂遵脉貌柏狱猜怜惑陶兽帐饰贷昌叙躺钢沟寄扶铺邓寿惧询汤盗肥尝匆辉奈扣廷澳嘛董迁凝慰厌脏腾幽怨鞋丢埋泉涌辖躲晋紫艰巍偷尖忠累炎暂估泛荒偿横拒瑞忆孤鼻闹羊呆厉衡胞零穷舍码赫婆魂灾洪腿胆津俗辩胸晓劲贫仁偶辑邦恢赖圈摸仰润堆碰艇稍迟辆废净凶署壁御奉旋冬矿抬蛋晨伏吹鸡倍糊秦盾杯租骑乏隆诊奴摄丧污渡旗甘耐凭扎抢绪粗肩梁幻菲皆碎宙叔岩荡综爬荷悉蒂返井壮薄悄扫敏碍殖详迪矛霍允幅撒剩凯颗骂赏液番箱贴漫酸郎腰舒眉忧浮辛恋餐吓挺励辞艘键伍峰尺昨黎辈贯侦滑券崇扰宪绕趋慈乔阅汗枝拖墨胁插箭腊粉泥氏彭拔骗凤慧媒佩愤扑龄驱惜豪掩兼跃尸肃帕驶堡届欣惠册储飘桑闲惨洁踪勃宾频仇磨递邪撞拟滚奏巡颜剂绩贡疯坡瞧截燃焦殿伪柳锁逼颇昏劝呈搜勤戒驾漂饮曹朵仔柔俩孟腐幼践籍牧凉牲佳娜浓芳稿竹腹跌逻垂遵脉貌柏狱猜怜惑陶兽帐饰贷昌叙躺钢沟寄扶铺邓寿惧询汤盗肥尝匆辉奈扣廷澳嘛董迁凝慰厌脏腾幽怨鞋丢埋泉涌辖躲晋紫艰巍偷'
)


def atlas_ink():
    pak = open(P_PAK, 'rb').read()
    recs = L.parse_pak_records(pak)
    r = [x for x in recs if x['name'] == 'new_font_revised'][0]
    cont = pak[r['px_off']:r['px_off'] + r['px']]
    tex, _e, _pk, _segs = F.atlas_engine_image(cont, 512, 512, 19)
    return tex == 0


def render16(ch):
    fnt = ImageFont.truetype(TTF, 16)
    img = Image.new('L', (32, 32), 255)
    ImageDraw.Draw(img).text((8, 8), ch, font=fnt, fill=0)
    a = np.asarray(img)[8:24, 8:24] < 128
    return a[:, 0::2] | a[:, 1::2]


def shift_or_xor(t, crop, dx, dy):
    H, W = crop.shape
    tt = np.zeros_like(crop)
    src0y, src0x = max(0, -dy), max(0, -dx)
    dst0y, dst0x = max(0, dy), max(0, dx)
    h = min(H - dst0y, H - src0y)
    w = min(W - dst0x, W - src0x)
    if h > 0 and w > 0:
        tt[dst0y:dst0y + h, dst0x:dst0x + w] = t[src0y:src0y + h, src0x:src0x + w]
    return int((tt != crop).sum())


def candidates():
    js = json.load(open(os.path.join(REPO, 'assets', 'charset', 'charset_compiled_zh16.json'),
                        encoding='utf-8'))
    out, seen = [], set()

    def add(s):
        for ch in s:
            if ch not in seen:
                seen.add(ch)
                out.append(ch)
    add(''.join(chr(c) for c in range(0x20, 0x7F)))
    add('，。！？：；、（）《》“”‘’…—·【】％＋－×÷／　')
    add(list(js['pair_of'].keys()))
    add(list(js['codes'].keys()))
    add(COMMON)
    return out


def lang_entries():
    raw = open(P_LANG, 'rb').read()
    blob = b''.join(s[0] for s in L.lzo_subs(raw))
    ents, used = L.parse_lang(blob)
    return ents


def split_codes(data):
    out = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if 0xA1 <= b < 0xAE and i + 1 < n and 0xA1 <= data[i + 1] < 0xFF:
            out.append(('pair', (b, data[i + 1])))
            i += 2
        else:
            out.append(('single', b))
            i += 1
    return out


def main():
    ink = atlas_ink()
    ft = json.load(open(P_FT, encoding='utf-8'))
    large = [f for f in ft['faces'] if f['name'] == 'large'][0]['recs']
    ents = lang_entries()
    cnt = Counter()
    for e in ents:
        for kind, c in split_codes(e.data):
            if kind == 'single' and (c >= 0xAE or (0x80 <= c < 0xA1)):
                cnt[c] += 1
    chars = candidates()
    tmpls = {}
    tmpl_list = []
    for ch in chars:
        t = render16(ch)
        if t.any():
            tmpl_list.append((ch, t))
    print('候选 %d' % len(tmpl_list))
    DX = list(range(-1, 5))
    DY = list(range(-2, 3))
    out = {}
    for code in sorted(cnt):
        idx = code - 0x20
        b0, adv, u0, v0, u1, v1 = large[idx]
        crop = ink[v0:v1, u0:u1]
        h, w = crop.shape
        scored = []
        for ch, t in tmpl_list:
            if t.shape != (16, 8):
                continue
            if (w, h) == (8, 16):
                best = min(shift_or_xor(t, crop, dx, dy) for dx in DX for dy in DY)
            else:
                # 小矩形：只比左上 w×h 区域（不平移，先标记）
                best = int((t[:h, :w] != crop).sum())
            scored.append((best, ch))
        scored.sort()
        best = scored[0]
        second = scored[1]
        conf = 'high' if best[0] == 0 and second[0] >= 2 else (
            'medium' if best[0] <= 2 and second[0] >= best[0] + 2 else 'low')
        out[code] = dict(code=code, code_hex='%02X' % code, rect=[u0, v0, u1, v1],
                         adv=adv, char=best[1], dist=best[0], second=second[0],
                         second_char=second[1], conf=conf, count=cnt[code],
                         top=[(s, c) for s, c in scored[:5]])
        print('%02X rect=(%3d,%3d,%3d,%3d) %s char=%r dist=%d second=%r/%d  count=%d'
              % (code, u0, v0, u1, v1, conf, best[1], best[0], second[1], second[0], cnt[code]))
    json.dump(out, open(os.path.join(JS, 'js19_single_map.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    from collections import Counter as C
    print('置信度:', C(v['conf'] for v in out.values()))
    print('[out] js19_single_map.json')


if __name__ == '__main__':
    main()
