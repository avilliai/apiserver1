DISPLAY_NAME = "Hololive TTS 文本转语音"
DESCRIPTION = "文本转语言。可用角色查看【Example Code】页面"
# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 3000



POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/tts",
    "params": {
            "text": "こんにちは、世界！",
            "speaker": "AZKi",
        "lang": "JP"
        }
}
EXAMPLE = """
'''
可用角色
['MoriCalliope', 'TakanashiKiara', 'NinomaeInanis', 'GawrGura', 'AmeliaWatson', 'IRyS', 
'TsukumoSana', 'CeresFauna', 'OuroKronii', 'NanashiMumei', 'HakosBaelz', 'ShioriNovella', 
'KosekiBijou', 'NerissaRavencroft', 'AyundaRisu', 'MoonaHoshinova', 'AiraniIofifteen', 
'KureijiOllie', 'AnyaMelfissa', 'VestiaZeta', 'TokinoSora', 'SakuraMiko', 'HoshimachiSuisei', 
'AZKi', 'YozoraMel', 'ShirakamiFubuki', 'NatsuiroMatsuri', 'AkiRosenthal', 'AkaiHaato', 
'MinatoAqua', 'NakiriAyame', 'OozoraSubaru', 'NekomataOkayu', 'UsadaPekora', 'UruhaRushia', 
'ShiranuiFlare', 'ShiroganeNoel', 'HoushouMarine', 'AmaneKanata', 'TsunomakiWatame', 'TokoyamiTowa', 
'HimemoriLuna', 'YukihanaLamy', 'MomosuzuNene', 'OmaruPolka', 'LaplusDarknesss', 'TakaneLui', 
'HakuiKoyori', 'SakamataChloe', 'IchijouRirika', 'JuufuuteiRaden',    
"agnes_digital_爱丽数码_アグネスデジタル",
"curren_chan_真机伶_カレンチャン",
"matikane_fukukitaru_待兼福来_マチカネフクキタル",
"matikane_tannhauser_待兼诗歌剧_マチカネタンホイサ",
"mejiro_mcqueen_目白麦昆_メジロマックイーン",
"natuki",
"nice_nature_优秀素质_ナイスネイチャ",
"rice_shower_米浴_ライスシャワー",
"satono_diamond_里见光钻_サトノダイヤモンド"]
'''
import base64
import requests
BASE = "http://api.apollodorus.xyz"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/tts",
    json = {
            "text": "こんにちは、世界！",
            "speaker": "AZKi",
        "lang": "JP"
        },
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
print(r.json())
"""
