DISPLAY_NAME = "Hololive TTS 文本转语音"
DESCRIPTION = "文本转语言"
# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 3000



POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/tts",
    "params": {
            "text": "早上好，今天你起的好早",
            "speaker": "AZKI",
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
'HakuiKoyori', 'SakamataChloe', 'IchijouRirika', 'JuufuuteiRaden']
'''
import base64
import requests
BASE = "http://api.apollodorus.xyz"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/tts",
    json = {
            "text": "早上好，今天你起的好早",
            "speaker": "AZKI",
        "lang": "JP"
        },
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
print(r.json())
"""
