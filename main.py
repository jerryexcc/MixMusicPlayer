import sys
import os
import tempfile
import pygame
import random
from mutagen.mp3 import MP3
from mutagen.wave import WAVE

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

from contextlib import contextmanager

# 在檔案最上方，與其他 def 工具函數放在一起
@contextmanager
def suppress_c_stderr():
    """系統級別的攔截器，用來吞掉底層 C 函式庫 (如 libmpg123) 的煩人 log"""
    try:
        # 開啟作業系統的無底洞 (Windows 的 NUL，Mac/Linux 的 /dev/null)
        null_fd = os.open(os.devnull, os.O_RDWR)
        # 記住當前真正的 stderr (file descriptor 通常是 2)
        save_fd = os.dup(sys.stderr.fileno())
        # 將系統的 stderr 強制切換到黑洞
        os.dup2(null_fd, sys.stderr.fileno())
        
        yield # 執行括號內的程式碼
        
    finally:
        # 執行完畢後，把 stderr 切回原本的樣子，並關閉資源
        os.dup2(save_fd, sys.stderr.fileno())
        os.close(null_fd)
        os.close(save_fd)

# ---------------------------------------------------------
# 共用工具與驗證
# ---------------------------------------------------------
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

def format_time(seconds):
    if seconds is None or seconds <= 0:
        return "未知"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"

# ---------------------------------------------------------
# 背景執行緒
# ---------------------------------------------------------
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
        self.add_btn.clicked.connect(self.add_songs_action)
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.accept)
        
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
        self.status_label.setStyleSheet("")
        
        for item in items:
            is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
            
            duration_str = ""
            if not is_folder:
                duration_millis = item.get('audioMediaMetadata', {}).get('durationMillis')
                if duration_millis:
                    seconds = int(duration_millis) / 1000
                    duration_str = f" [{format_time(seconds)}]"
                    item['duration_sec'] = seconds
            
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
            
        self.songs_added_signal.emit(songs)
        
        original_text = f"目前目錄共有 {self.list_widget.count()} 個項目 (雙擊進入資料夾)"
        self.status_label.setText(f"✅ 成功加入 {len(songs)} 首音樂！")
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self.list_widget.clearSelection()
        
        QTimer.singleShot(2000, lambda: self.reset_status_label(original_text))

    def reset_status_label(self, text):
        if "✅" in self.status_label.text():
            self.status_label.setText(text)
            self.status_label.setStyleSheet("")

# ---------------------------------------------------------
# 主視窗 (GUI)
# ---------------------------------------------------------
class MusicPlayerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("懶人雲端播放器 (Drive + Local)")
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
        
        self.control_layout = QHBoxLayout()
        
        self.prev_btn = QPushButton("⏮ 上一首")
        self.prev_btn.clicked.connect(self.play_prev_song)
        
        self.play_btn = QPushButton("▶ 播放")
        self.play_btn.clicked.connect(self.play_selected_music)
        
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.clicked.connect(self.stop_music)
        
        self.next_btn = QPushButton("⏭ 下一首")
        self.next_btn.clicked.connect(self.play_next_song)
        
        self.remove_btn = QPushButton("🗑️ 移除")
        self.remove_btn.clicked.connect(self.remove_selected_music)
        
        self.loop_mode_btn = QPushButton("🔁 列表循環")
        self.loop_mode_btn.clicked.connect(self.toggle_loop_mode)
        
        self.control_layout.addWidget(self.prev_btn)
        self.control_layout.addWidget(self.play_btn)
        self.control_layout.addWidget(self.stop_btn)
        self.control_layout.addWidget(self.next_btn)
        self.control_layout.addWidget(self.remove_btn)
        self.control_layout.addWidget(self.loop_mode_btn)
        self.layout.addLayout(self.control_layout)
        
        self.setCentralWidget(self.central_widget)
        
        self.music_data = []
        self.current_temp_file = None 
        self.current_playing_song = None
        
        self.is_playing = False
        self.loop_mode = "LIST"
        self.song_counter = 0
        
        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.check_playback_status)
        self.playback_timer.start(200) 

    def check_playback_status(self):
        # 只要我們標記為正在播放，且 pygame 底層說「我沒在播了」，那就是自然播完
        if self.is_playing and not pygame.mixer.music.get_busy():
            self.is_playing = False # 解除標記，避免重複觸發
            self.play_next_song()

    def toggle_loop_mode(self):
        if self.loop_mode == "LIST":
            self.loop_mode = "SINGLE"
            self.loop_mode_btn.setText("🔂 單曲循環")
            # 順序維持不變

        elif self.loop_mode == "SINGLE":
            self.loop_mode = "SHUFFLE"
            self.loop_mode_btn.setText("🔀 隨機模式")
            # 將資料實體打散，並重繪 UI
            random.shuffle(self.music_data)
            self.refresh_playlist_ui()

        elif self.loop_mode == "SHUFFLE":
            self.loop_mode = "RANDOM"
            self.loop_mode_btn.setText("🎲 盲盒模式")
            # 利用 original_order 屬性，將資料恢復為最初始的順序，並重繪 UI
            self.music_data.sort(key=lambda x: x.get('original_order', 0))
            self.refresh_playlist_ui()

        else:
            self.loop_mode = "LIST"
            self.loop_mode_btn.setText("🔁 列表循環")
            # 確保維持初始順序 (預防萬一)
            self.music_data.sort(key=lambda x: x.get('original_order', 0))
            self.refresh_playlist_ui()

    def play_prev_song(self):
        if not self.music_data:
            return
            
        current_index = self.playlist_widget.currentRow()
        total_songs = len(self.music_data)
        
        if self.loop_mode == "SINGLE":
            # 單曲循環：保持當前歌曲重播
            next_index = current_index if current_index >= 0 else 0
            
        elif self.loop_mode == "RANDOM":
            # 盲盒模式：因為是完全獨立的隨機事件，上一首也是隨機抽
            next_index = random.randint(0, total_songs - 1)
            
        else:
            # "LIST" (列表) 與 "SHUFFLE" (隨機模式：已實體打散陣列)
            if current_index <= 0:
                # 如果已經是第一首，或者是沒選取，就跳到最後一首 (頭尾相連)
                next_index = total_songs - 1
            else:
                next_index = current_index - 1
                
        self.playlist_widget.setCurrentRow(next_index)
        self.play_selected_music()

    def play_next_song(self):
        if not self.music_data:
            return
            
        current_index = self.playlist_widget.currentRow()
        total_songs = len(self.music_data)
        
        if self.loop_mode == "SINGLE":
            next_index = current_index if current_index >= 0 else 0
            
        elif self.loop_mode == "RANDOM":
            next_index = random.randint(0, total_songs - 1)
            
        else:
            if current_index < 0:
                next_index = 0
            else:
                next_index = (current_index + 1) % total_songs
                
        self.playlist_widget.setCurrentRow(next_index)
        self.play_selected_music()

    def open_drive_explorer(self):
        dialog = DriveExplorerDialog(self)
        dialog.songs_added_signal.connect(self.on_songs_added_from_drive)
        dialog.exec()

    def on_songs_added_from_drive(self, selected_songs):
        for song in selected_songs:
            duration = song.get('duration_sec', 0)
            time_str = format_time(duration)
            
            self.playlist_widget.addItem(f"☁️ [{time_str}] {song['name']}")
            self.music_data.append({
                'name': song['name'],
                'source': 'drive',
                'id': song['id'],
                'duration': duration,
                'original_order': self.song_counter
            })
            self.song_counter += 1
        self.status_label.setText(f"狀態：最新加入了 {len(selected_songs)} 首雲端音樂")

    def load_local_music(self):
        files, _ = QFileDialog.getOpenFileNames(self, "選擇本機音樂檔案", "", "Audio Files (*.mp3 *.wav)")
        if files:
            for file_path in files:
                file_name = os.path.basename(file_path)
                
                duration_sec = 0
                try:
                    if file_path.lower().endswith('.mp3'):
                        audio = MP3(file_path)
                        duration_sec = audio.info.length
                    elif file_path.lower().endswith('.wav'):
                        audio = WAVE(file_path)
                        duration_sec = audio.info.length
                except Exception:
                    pass
                
                time_str = format_time(duration_sec)
                
                self.playlist_widget.addItem(f"💻 [{time_str}] {file_name}")
                self.music_data.append({
                    'name': file_name,
                    'source': 'local',
                    'path': file_path,
                    'duration': duration_sec,
                    'original_order': self.song_counter
                })
                self.song_counter += 1
            self.status_label.setText(f"狀態：已加入 {len(files)} 首本機音樂")

    def remove_selected_music(self):
        selected_index = self.playlist_widget.currentRow()
        if selected_index < 0:
            return
            
        song_to_remove = self.music_data[selected_index]
        
        if self.current_playing_song == song_to_remove:
            self.stop_music()
            self.current_playing_song = None
        
        self.playlist_widget.takeItem(selected_index)
        del self.music_data[selected_index]
        
        self.status_label.setText(f"狀態：已移除 [{song_to_remove['name']}]")

    def play_selected_music(self):
        selected_index = self.playlist_widget.currentRow()
        if selected_index < 0:
            return
            
        # 👇 防呆：如果前一首歌還在下載，先強制停止下載執行緒
        if hasattr(self, 'download_thread') and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()
            self.progress_bar.setVisible(False)
            
        selected_song = self.music_data[selected_index]
        self.stop_music()
        
        self.current_playing_song = selected_song 
        
        if selected_song['source'] == 'local':
            self.status_label.setText(f"狀態：🎵 播放本機音樂 [{selected_song['name']}]")
            self.play_btn.setEnabled(False)
            
            try:
                with suppress_c_stderr():
                    pygame.mixer.music.load(selected_song['path'])
                pygame.mixer.music.play()
                self.is_playing = True
            except Exception as e:
                self.status_label.setText(f"狀態：播放失敗 ({e})")
            
            self.play_btn.setEnabled(True)
            
        elif selected_song['source'] == 'drive':
            self.status_label.setText(f"狀態：正在下載雲端音樂 [{selected_song['name']}]...")
            self.play_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            # 正在下載，這時候還不算播放中
            self.is_playing = False 
            
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
        
        # 👇 新增：趁著檔案已經在本地，馬上解析長度！
        duration_sec = 0
        try:
            audio = MP3(temp_path)
            duration_sec = audio.info.length
        except Exception:
            pass # 如果解析失敗就算了
            
        # 如果解析成功，立刻更新畫面與資料陣列
        if duration_sec > 0:
            current_index = self.playlist_widget.currentRow()
            if current_index >= 0:
                # 更新背後資料
                self.music_data[current_index]['duration'] = duration_sec
                # 重新組合文字 (例如從 ☁️ [未知] 變成 ☁️ [04:13])
                song_name = self.music_data[current_index]['name']
                time_str = format_time(duration_sec)
                new_text = f"☁️ [{time_str}] {song_name}"
                # 更新 UI 畫面
                self.playlist_widget.item(current_index).setText(new_text)
        
        try:
            with suppress_c_stderr():
                pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()
            self.is_playing = True
            self.status_label.setText("狀態：🎵 播放雲端音樂中...")
        except Exception as e:
            self.status_label.setText(f"狀態：播放失敗 ({e})")

    def stop_music(self):
        # 只要使用者按停止，就解除播放標記，巡邏員就不會誤以為是播完
        self.is_playing = False
        
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
    
    def refresh_playlist_ui(self):
        self.playlist_widget.clear()
        
        for song in self.music_data:
            duration = song.get('duration', 0)
            time_str = format_time(duration)
            icon = "☁️" if song['source'] == 'drive' else "💻"
            self.playlist_widget.addItem(f"{icon} [{time_str}] {song['name']}")
            
        # 恢復選取「正在播放的歌曲」，讓反白跟著歌走
        if self.current_playing_song in self.music_data:
            current_idx = self.music_data.index(self.current_playing_song)
            self.playlist_widget.setCurrentRow(current_idx)

    def closeEvent(self, event):
        self.stop_music()
        pygame.mixer.quit()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MusicPlayerWindow()
    window.show()
    sys.exit(app.exec())