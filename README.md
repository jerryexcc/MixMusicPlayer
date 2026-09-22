MixMusicPlayer (混合音樂播放器)
===
發想:
1. 由於Google Drive上有長年累積的音樂檔案, 但又不想要一一下載下來, 搭配本機端的檔案一起播放
2. 雖然Google Drive可以直接聽音樂, 但無法連續播放下一首歌曲或是隨機播放

綜合以上原因便產生了這個想法, 開發了這款混合雲端和本機音樂的播放器。

* * *
使用技術:
- Python 3.13
- Google Drive
- Pygame (解決Windows和Mac跨平台音樂播放API不相容的問題)
- PyQt6 (提供GUI介面)


# 使用前須知
- 因涉及到Google API，初次使用會跳轉到Google登入畫面, 登入並同意授權後即可正常使用
- clone下來後須先到[Google Cloud Console](https://console.cloud.google.com/) 建立專案並至OAuth 2.0 用戶端中建立憑證並下載credentials.json
- 將下載的credentials.json放到同一個資料夾內
- 首次執行會開啟瀏覽器要求登入, 登入後瀏覽器會顯示要求讀取Google Drive權限, 同意授權後即可正常使用
- 此播放器目前僅支援從Google Drive串流播放MP3檔案和本機檔案混合播放


***

MixMusicPlayer (Hybrid Music Player)
===
Inspiration:
1. Having accumulated music files on Google Drive over the years without wanting to download them one by one to play alongside local files.
2. Although Google Drive allows playing audio files directly, it cannot continuously play the next track or shuffle songs.

Combining the reasons above, this idea was born to develop a player that seamlessly blends cloud and local music.

* * *
Technologies Used:
- Python 3.13
- Google Drive
- Pygame (Resolves cross-platform audio playback API incompatibilities between Windows and Mac)
- PyQt6 (Provides GUI)


# Notice Before Use
- Because Google APIs are involved, the application will redirect to a Google login page on first launch. After logging in and granting authorization, it can be used normally.
- After cloning the repository, go to [Google Cloud Console](https://console.cloud.google.com/) to create a project, create credentials under OAuth 2.0 Client IDs, and download credentials.json.
- Place the downloaded credentials.json in the same folder.
- On first run, a browser will open asking you to log in and request permission to read Google Drive. Grant authorization to use the application normally.
- Currently, this player only supports streaming MP3 files from Google Drive and playing them interchangeably with local files.
