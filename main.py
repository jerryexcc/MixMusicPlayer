import sys
import os
import tempfile
import pygame
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QListWidget, QLabel, QProgressBar, QHBoxLayout,
                             QFileDialog, QDialog, QAbstractItemView, QListWidgetItem)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

# --- 背景執行緒 ---
class DriveFolderLoaderThread(QThread):
    items_fetched_signal = pyqtSignal(list)

    def __init__(self, folder_id='root'):
        super().__init__()
        self.folder_id = folder_id

    def run(self):
        creds = get_credentials()
        service = build('drive', 'v3', credentials=creds)
        
        query = f"'{self.folder_id}' in parents and trashed = false and (mimeType='application/vnd.google-apps.folder' or name contains '.mp3')"
        
        all_items = []
        page_token = None
        
        while True:
            results = service.files().list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id, name, mimeType)",
                orderBy="folder, name",
                pageToken=page_token
            ).execute()
            
            all_items.extend(results.get('files', []))
            page_token = results.get('nextPageToken', None)
            
            if not page_token:
                break
                
        self.items_fetched_signal.emit(all_items)

class DriveDownloadThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    
    def __init__(self, file_id):
        super().__init__()
        self.file_id = file_id

    def run(self):
        creds = get_credentials()
        service = build('drive', 'v3', credentials=creds)
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_path = temp_file.name
        
        request = service.files().get_media(fileId=self.file_id)
        downloader = MediaIoBaseDownload(temp_file, request)
        
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                self.progress_signal.emit(int(status.progress() * 100))
                
        temp_file.close()
        self.finished_signal.emit(temp_path)

# ---------------------------------------------------------
# 雲端檔案總管視窗 (Toast 版本)
# ---------------------------------------------------------
class DriveExplorerDialog(QDialog):
    # 自訂訊號：當使用者按下加入時，把歌曲清單發送給主視窗
    songs_added_signal = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("雲端硬碟瀏覽器")
        self.resize(500, 400)
        self.layout = QVBoxLayout(self)
        
        self.nav_layout = QHBoxLayout()
        self.back_btn = QPushButton("⬅️ 回上一層")
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self.go_back)
        self.nav_layout.addWidget(self.back_btn)
        
        self.status_label = QLabel("正在讀取根目錄...")
        self.nav_layout.addWidget(self.status_label)
        self.layout.addLayout(self.nav_layout)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.layout.addWidget(self.list_widget)
        
        self.btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("加入選取的音樂")
        self.add_btn.clicked.connect(self.add_songs_action) # 改為觸發自訂函數，不關閉視窗
        
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.accept) # 只有按關閉才會真的關掉視窗
        
        self.btn_layout.addWidget(self.add_btn)
        self.btn_layout.addWidget(self.close_btn)
        self.layout.addLayout(self.btn_layout)
        
        self.current_folder_id = 'root'
        self.history_stack = []
        
        self.load_folder(self.current_folder_id)
        
    def load_folder(self, folder_id):
        self.list_widget.clear()
        self.status_label.setText("讀取中，請稍候...")
        self.list_widget.setEnabled(False)
        
        self.loader_thread = DriveFolderLoaderThread(folder_id)
        self.loader_thread.items_fetched_signal.connect(self.on_items_loaded)
        self.loader_thread.start()
        
    def on_items_loaded(self, items):
        self.list_widget.setEnabled(True)
        self.status_label.setText(f"目前目錄共有 {len(items)} 個項目 (雙擊進入資料夾)")
        self.status_label.setStyleSheet("") # 確保文字顏色正常
        
        for item in items:
            is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
            icon = "📁" if is_folder else "🎵"
            list_item = QListWidgetItem(f"{icon} {item['name']}")
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.list_widget.addItem(list_item)
            
    def on_item_double_clicked(self, item):
        file_data = item.data(Qt.ItemDataRole.UserRole)
        if file_data['mimeType'] == 'application/vnd.google-apps.folder':
            self.history_stack.append(self.current_folder_id)
            self.current_folder_id = file_data['id']
            self.back_btn.setEnabled(True)
            self.load_folder(self.current_folder_id)
            
    def go_back(self):
        if self.history_stack:
            self.current_folder_id = self.history_stack.pop()
            if not self.history_stack:
                self.back_btn.setEnabled(False)
            self.load_folder(self.current_folder_id)
            
    def add_songs_action(self):
        songs = []
        for item in self.list_widget.selectedItems():
            file_data = item.data(Qt.ItemDataRole.UserRole)
            if file_data['mimeType'] != 'application/vnd.google-apps.folder':
                songs.append(file_data)
                
        if not songs:
            return
            
        # 1. 透過訊號把歌送到主視窗
        self.songs_added_signal.emit(songs)
        
        # 2. 實作 Toast 動態提示 (變更文字與顏色，2秒後恢復)
        original_text = f"目前目錄共有 {self.list_widget.count()} 個項目 (雙擊進入資料夾)"
        self.status_label.setText(f"✅ 成功加入 {len(songs)} 首音樂！")
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;") # 給一點綠色提示
        
        # 清除選取狀態，讓使用者知道已經加過了
        self.list_widget.clearSelection()
        
        # 設定 QTimer，2000 毫秒 (2秒) 後把標籤改回原本的樣子
        QTimer.singleShot(2000, lambda: self.reset_status_label(original_text))

    def reset_status_label(self, text):
        # 檢查是否還在同一個資料夾，避免切換資料夾後文字被蓋掉
        if "✅" in self.status_label.text():
            self.status_label.setText(text)
            self.status_label.setStyleSheet("")

# ---------------------------------------------------------
# 主視窗 (GUI)
# ---------------------------------------------------------
class MusicPlayerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("跨平台混合播放器 (Drive + Local)")
        self.resize(550, 500)
        
        pygame.mixer.init()
        
        self.central_widget = QWidget()
        self.layout = QVBoxLayout(self.central_widget)
        
        self.status_label = QLabel("狀態：等待載入音樂...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.status_label)
        
        self.btn_layout = QHBoxLayout()
        self.load_drive_btn = QPushButton("☁️ 開啟雲端音樂資料夾")
        self.load_drive_btn.clicked.connect(self.open_drive_explorer)
        self.btn_layout.addWidget(self.load_drive_btn)
        
        self.load_local_btn = QPushButton("📂 載入本機音樂")
        self.load_local_btn.clicked.connect(self.load_local_music)
        self.btn_layout.addWidget(self.load_local_btn)
        self.layout.addLayout(self.btn_layout)
        
        self.playlist_widget = QListWidget()
        self.layout.addWidget(self.playlist_widget)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)
        
        # --- 控制區新增「刪除」按鈕 ---
        self.control_layout = QHBoxLayout()
        self.play_btn = QPushButton("▶ 播放選取音樂")
        self.play_btn.clicked.connect(self.play_selected_music)
        
        self.stop_btn = QPushButton("⏹ 停止播放")
        self.stop_btn.clicked.connect(self.stop_music)
        
        self.remove_btn = QPushButton("🗑️ 移除選取")
        self.remove_btn.clicked.connect(self.remove_selected_music)
        
        self.control_layout.addWidget(self.play_btn)
        self.control_layout.addWidget(self.stop_btn)
        self.control_layout.addWidget(self.remove_btn)
        self.layout.addLayout(self.control_layout)
        
        self.setCentralWidget(self.central_widget)
        
        self.music_data = []
        self.current_temp_file = None 
        self.current_playing_song = None # 新增這行，用來記住現在播的是哪首

    def open_drive_explorer(self):
        dialog = DriveExplorerDialog(self)
        # 把雲端視窗發出來的訊號，接回主視窗的函數
        dialog.songs_added_signal.connect(self.on_songs_added_from_drive)
        dialog.exec() # 開啟對話框

    def on_songs_added_from_drive(self, selected_songs):
        # 接收到訊號時，把歌加入清單
        for song in selected_songs:
            self.playlist_widget.addItem(f"☁️ [雲端] {song['name']}")
            self.music_data.append({
                'name': song['name'],
                'source': 'drive',
                'id': song['id']
            })
        self.status_label.setText(f"狀態：最新加入了 {len(selected_songs)} 首雲端音樂")

    def load_local_music(self):
        files, _ = QFileDialog.getOpenFileNames(self, "選擇本機音樂檔案", "", "Audio Files (*.mp3 *.wav)")
        if files:
            for file_path in files:
                file_name = os.path.basename(file_path)
                self.playlist_widget.addItem(f"💻 [本機] {file_name}")
                self.music_data.append({
                    'name': file_name,
                    'source': 'local',
                    'path': file_path
                })
            self.status_label.setText(f"狀態：已加入 {len(files)} 首本機音樂")

    # --- 實作刪除邏輯 ---
    def remove_selected_music(self):
        selected_index = self.playlist_widget.currentRow()
        if selected_index < 0:
            return
            
        song_to_remove = self.music_data[selected_index]
        
        # 只有當「準備刪除的歌」剛好就是「正在播放的歌」時，才需要停止音樂
        if self.current_playing_song == song_to_remove:
            self.stop_music()
            self.current_playing_song = None
        
        # 從畫面清單中移除
        self.playlist_widget.takeItem(selected_index)
        
        # 從背後的資料陣列中移除
        del self.music_data[selected_index]
        
        self.status_label.setText(f"狀態：已移除 [{song_to_remove['name']}]")

    def play_selected_music(self):
        selected_index = self.playlist_widget.currentRow()
        if selected_index < 0:
            return
            
        selected_song = self.music_data[selected_index]
        self.stop_music()
        
        # 記住現在準備播放的這首歌
        self.current_playing_song = selected_song 
        
        if selected_song['source'] == 'local':selected_index = self.playlist_widget.currentRow()
        if selected_index < 0:
            return
            
        selected_song = self.music_data[selected_index]
        self.stop_music()
        
        # 記住現在準備播放的這首歌
        self.current_playing_song = selected_song 
        
        if selected_song['source'] == 'local':
            self.status_label.setText(f"狀態：🎵 播放本機音樂 [{selected_song['name']}]")
            self.play_btn.setEnabled(False)
            
            try:
                pygame.mixer.music.load(selected_song['path'])
                pygame.mixer.music.play()
            except Exception as e:
                self.status_label.setText(f"狀態：播放失敗 ({e})")
            
            self.play_btn.setEnabled(True)
            
        elif selected_song['source'] == 'drive':
            self.status_label.setText(f"狀態：正在緩衝雲端音樂 [{selected_song['name']}]...")
            self.play_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            self.download_thread = DriveDownloadThread(selected_song['id'])
            self.download_thread.progress_signal.connect(self.update_progress)
            self.download_thread.finished_signal.connect(self.on_download_finished)
            self.download_thread.start()

    def update_progress(self, percent):
        self.progress_bar.setValue(percent)

    def on_download_finished(self, temp_path):
        self.progress_bar.setVisible(False)
        self.play_btn.setEnabled(True)
        self.current_temp_file = temp_path
        
        try:
            pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()
            self.status_label.setText("狀態：🎵 播放雲端音樂中...")
        except Exception as e:
            self.status_label.setText(f"狀態：播放失敗 ({e})")

    def stop_music(self):
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        
        try:
            pygame.mixer.music.unload()
        except AttributeError:
            pass
            
        self.status_label.setText("狀態：已停止播放")
        self.cleanup_temp_file()

    def cleanup_temp_file(self):
        if self.current_temp_file and os.path.exists(self.current_temp_file):
            try:
                os.remove(self.current_temp_file)
                self.current_temp_file = None
            except Exception:
                pass

    def closeEvent(self, event):
        self.stop_music()
        pygame.mixer.quit()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MusicPlayerWindow()
    window.show()
    sys.exit(app.exec())