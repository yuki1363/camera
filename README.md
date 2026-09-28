# capper-monitor

ラズパイ5とカメラでキャッパーボックス（キャップホッパー）内部の「ライン」を監視し、
ラインが露出（キャップ残量低下）を検知したらPLCへ信号を出力するシステムです。

- ラインを検知したら、GPIO出力（絶縁モジュール経由）でPLCのデジタル入力へ
  「キャップ数減少」信号を送ります。
- パトライト黄色の点灯・消灯は**PLC側のラダーロジックがこの信号を使って行います**
  （本リポジトリはラズパイ→PLCへの1本の出力のみを担当し、パトライトを直接制御する
  コードは含みません）。
- キャップ投入中（補充作業中）を動き検知で判定し、その間は出力を点滅させます。
  PLC側のラダーは、受け取ったデジタル入力（DI）をそのままパトライト出力（DO）へ
  パススルーするだけで構いません（PLC側にタイマー回路は不要です）。
- ラインが見えなくなった場合、または物理リセットボタン／PLCからのリセット信号を
  受けた場合に出力をOFFへ戻します（非ラッチ方式。詳細は下記「リセットの挙動」参照）。
- スマホでライブ映像・検知状態を確認できるWi-Fi監視ページ（任意機能）を搭載しています。

## 動作要件

- Raspberry Pi 5（Raspberry Pi OS Bookworm以降を推奨、NetworkManager前提）
- カメラ: 純正CSIカメラモジュール（picamera2）またはUSBウェブカメラ（OpenCV）
- Python 3.11+

## ハードウェア構成（電圧差対策・絶縁インターフェース）

ラズパイ5のGPIOは **3.3Vロジック**、PLCは **DC24V** 系です。直結すると破損・誤動作の
危険があるため、両方向とも必ず絶縁インターフェースを介してください。

### 出力側（ラズパイ→PLC、キャップ数減少信号）

- **PhotoMOS/SSR（無接点半導体リレー、例: Panasonic AQY, Toshiba TLP, Omron G3VM系）を推奨。**
  機械式リレーは数mA〜十数mAというドライサーキット領域では接点酸化による接触不良リスクがあり、
  接点バウンス（数ms〜十数ms）がPLC側の誤カウントにつながるためです。
  機械式リレーを使う場合はPLC入力フィルタ時定数をバウンス時間より十分長く設定してください。
- モジュールのIN端子しきい値がPi5の3.3Vロジックに対応しているか、データシートで確認してください。
  多くの汎用モジュールはVCC=5V基準でしきい値判定しており、3.3Vでは電圧マージンが不足する
  場合があります。その場合はGPIOとモジュールの間に小信号トランジスタ（2SC1815等）／
  ロジックレベルMOSFET／ダーリントンアレイIC（ULN2803A等）によるバッファ段を挿入してください。
- 出力の無電圧接点をPLCの24V入力回路に直列に挿入する形で結線します（ラズパイ側の3.3Vと
  PLC側の24Vが電気的に直結しません）。
- 起動時は必ず安全側（OFF）に初期化されます（`gpio.alarm_output` の `initial_value=False`）。

### 入力側（PLC→ラズパイ、リセット信号／NPNシンク出力）

- フォトカプラ絶縁の「24V→3.3V/5V DC入力変換モジュール」を使用します。
- 結線: `PLCの24V+ → 電流制限抵抗 → 絶縁モジュール入力LED → PLCのNPN出力端子（ON時にGNDへ導通）`。
  市販モジュールは制限抵抗を基板内蔵済みのものが多いため、二重に外付け抵抗を入れないよう
  データシートを確認してください。自作する場合の抵抗値目安式:
  `R ≒ (Vs − Vf_LED − Vce_sat) / I_LED`（例: Vs=24V, Vf_LED≒1.2V, I=10mA なら R≒2.2kΩ, 1/2W以上推奨）。
- 絶縁モジュール出力側（フォトトランジスタ側）をラズパイのGPIO入力へ接続し、
  `config.yaml` の `pull_up`/`active_high` をモジュールの出力極性に合わせて設定してください。

### 物理リセットボタン

- ラズパイの3.3Vドメイン内で完結する単純なGPIO入力（GPIO⇔GND、内部プルアップ）で構いません。
  絶縁は不要ですが、絶対にPLCの24V回路へ接続しないでください。

### グランド・ノイズ対策

- ラズパイのGND / PLC・24V電源系のGNDは異なる電位ドメインとして扱い、絶縁デバイス経由以外で
  直接結線しないでください。
- 24Vフィールド配線へのTVSダイオード/バリスタ追加、信号線のツイストペア化・シールド化
  （片端接地）、動力線からの物理的分離、GPIO入力への直列抵抗（100〜330Ω）、24V分岐回路への
  ヒューズ/PTC、フェルール端子処理を推奨します。

### GPIOピン割り当て（既定値、`config/config.yaml`で変更可能）

| 役割 | GPIO | 備考 |
|---|---|---|
| アラーム出力（→PLC DI） | 17 | 絶縁リレー/PhotoMOS経由 |
| 物理リセットボタン | 27 | GPIO⇔GND、内部プルアップ |
| PLCリセット入力 | 22 | 絶縁DC入力モジュール経由 |
| カメラ異常出力（任意） | 未設定 | `gpio.fault_output` で有効化可能 |

## セットアップ

```bash
git clone <このリポジトリ> /opt/capper-monitor
cd /opt/capper-monitor

# picamera2をaptで使う場合は --system-site-packages を付ける
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt

# picamera2を使う場合（CSIカメラ）
sudo apt install -y python3-picamera2
```

設定ファイルをコピーして編集します。

```bash
sudo mkdir -p /etc/capper-monitor
sudo cp config/config.yaml /etc/capper-monitor/config.yaml
sudo nano /etc/capper-monitor/config.yaml
```

### Camera Module 3（オートフォーカス搭載）を使う場合の注意

Raspberry Pi Camera Module 3 / 3 Wide（センサー`imx708`系）はオートフォーカス(AF)
搭載です。稼働中に連続AFが働くと再フォーカス時に一瞬映像がぼやけ、`baseline_diff`
方式の検知精度に影響しうるため、`config.yaml`の`camera.picamera2.autofocus_mode`で
制御します。

```yaml
camera:
  backend: picamera2
  picamera2:
    autofocus_mode: auto   # 既定値。起動時に1回だけAFを実行し、以後はその位置で固定
```

- `auto`（既定・推奨）: 起動時に自動でピントを合わせ、以後は固定します。手動でレンズ位置の数値を調べる必要はありません。
- `manual`: 現場で最適なレンズ位置が分かっている場合、`lens_position`（ディオプター値）を直接指定して固定します。
- `continuous`: 連続AFのまま動かします（**非推奨**。稼働中の再フォーカスでボケが発生し誤検知要因になりえます）。

IMX219（Camera Module 2やFreenove互換カメラ等、AF非搭載センサー）では、この設定は
自動的に無視されます（ログにINFOで記録されるだけで、エラーにはなりません）ので、
同じ`config.yaml`のテンプレートをカメラ機種によらず使い回せます。

### 自動露出(AE)・自動ホワイトバランス(AWB)を固定する仕組み

`auto_exposure: false` / `auto_white_balance: false`（既定・推奨）にした場合、
単純にAE/AWBを即座にOFFにするのではなく、**起動直後に一時的にAE/AWBを働かせて
収束させてから、その収束値で固定**します（`ae_awb_convergence_s`、既定1.5秒）。
単純にOFFにするだけだと、センサー起動直後の暫定的な（暗すぎる・色がおかしい）値の
まま固定されてしまうためです。

```yaml
camera:
  picamera2:
    ae_awb_convergence_s: 1.5   # 収束待ち時間(秒)。環境が暗い場合は伸ばす
```

現場の照明環境によっては収束に1.5秒以上かかる場合があるので、起動直後の映像が
まだ不安定な場合はこの値を大きくしてください。

設定を検証してから起動してください（`systemctl restart`前に必ず実行することを推奨）。

```bash
.venv/bin/python -m capper_monitor --config /etc/capper-monitor/config.yaml --check-config
```

## 現場調整（ROI・検知しきい値・基準フレーム）

カメラ・照明条件・ラインの実際の見え方は現物でしか確定できないため、`scripts/calibrate.py`
での現場調整が必須です。

> **注意**: `requirements.txt` の `opencv-python-headless` では `cv2.imshow` が使えません。
> 本ツールを実行する環境にのみ `pip install opencv-python`（GUI対応版）を追加インストールするか、
> 別PC・VNC経由で実行してください。

```bash
.venv/bin/pip install opencv-python  # このマシンでのみ、GUI対応版に切替
.venv/bin/python scripts/calibrate.py --config /etc/capper-monitor/config.yaml
```

キー操作:

| キー | 動作 |
|---|---|
| `r` | ROIを選択し直す |
| `b` | 基準フレーム（`baseline_diff`用）を複数枚撮影する（**キャップ満杯状態で実行**） |
| `a` | カメラ位置ズレ検知の基準フレームを1枚撮影する |
| `s` | 現在のROI・基準画像・設定値を保存する |
| `q` | 終了 |

プレビュー画面には現在の判定状態を色で表示します（パトライトと同じ配色）:
**緑=正常(NORMAL)** / **黄色点灯=アラーム(STEADY)** / **黄色点滅=キャップ投入中(BLINK)**。
本番運用中に同様の状態をスマホで確認したい場合は、下記のWeb監視ページが同じ配色で表示します。

## Wi-Fi監視機能（任意）

ラズパイをWi-Fiアクセスポイント化し、スマホのブラウザからライブ映像と検知状態を確認できます。

1. `config/config.yaml` の `web.enabled` を `true` にする。
2. Wi-FiをAPモードにセットアップする（一度きりのOSレベル設定）。

   ```bash
   sudo ./scripts/setup_wifi_ap.sh "CapperMonitor" "your-wpa2-passphrase"
   ```

   - 必ずWPA2パスフレーズ（8文字以上）を設定してください（オープンAPは不可）。
   - Wi-FiをAP化すると同じ無線でのインターネット接続（子機モード）は同時にできません。
     ラズパイ本体のインターネット接続が別途必要な場合は、有線LANまたはUSB Wi-Fiドングルの
     追加を検討してください。
3. スマホをそのSSIDに接続し、ブラウザで `http://<ラズパイのAP側IPアドレス>:8080/` を開く。

映像はメインの検知ループとは別解像度・低フレームレートでエンコードされ（`web.stream_*`設定）、
検知処理用のカメラアクセスとは競合しません（メインループが最新フレームを共有バッファに
書き込み、配信スレッドはそれを読むだけです）。

## systemdサービスとして常駐させる

```bash
sudo cp systemd/capper-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now capper-monitor
sudo systemctl status capper-monitor
journalctl -u capper-monitor -f
```

- `Restart=on-failure` + `RestartSec` + `StartLimitIntervalSec`/`StartLimitBurst` により、
  設定ミス等によるクラッシュループを防止します。
- `Type=notify` + `WatchdogSec` により、メインループがハングした場合にsystemdが検知して
  再起動します（`app.watchdog_enabled: true` の場合、追加パッケージ不要で標準ライブラリの
  `socket`のみで実装）。
- `lgpio` が `/dev/gpiochip*` へアクセスできるよう、サービス実行ユーザーを `gpio`/`video`
  グループに所属させてください（`SupplementaryGroups`設定済み）。

## リセットの挙動（非ラッチ方式）

「ラインが見えなくなったら」「リセットしたら」のどちらも独立して復帰条件になる、という
要件を文字通り解釈し、**非ラッチ方式**を採用しています。

- アラーム出力は基本的に「ライン検知の現在状態（チャタリング防止のON/OFF遅延つき）」を
  そのまま反映します。
- リセット（物理ボタン or PLC信号）は出力を**即座に強制OFF**にする上書き操作です。
- リセット後もラインが実際に見え続けている場合は、次の検知サイクルで再度ONになります
  （原因が解消していないため）。

運用上「キャップを補充してもラインが消えるまでは自動復帰させず、必ずリセット操作を
要求したい」という意図がある場合は、`capper_monitor/state_machine.py` の数行の変更で
ラッチ方式に切り替え可能です。

**リセットは常に独立して効きます。** カメラの位置ズレ検知がNGの間や、検知処理自体が
エラーになった場合（例: 解像度変更等でROIと基準画像の形状が合わない）も、検知結果を
信用できないフレームとして処理をスキップしますが、リセット操作だけは別扱いで必ず
即座に出力OFFへ反映されます（`capper_monitor/state_machine.py`の`force_normal()`）。
検知エラーはプロセスをクラッシュさせず、直前の出力値を保持したままログに記録し
（初回はERROR、以後30秒間隔で間引き、復旧時にINFO）、systemdのクラッシュループ防止
設定に頼らずに済むようにしています。

## 現場確認チェックリスト（本開発環境では検証不可・実機必須）

1. `picamera2`/libcamera の実挙動、CSIカメラの認識。Camera Module 3系では
   `autofocus_mode: auto`（既定）で起動時にピントが合い、以後の稼働中に再フォーカス
   （映像の一瞬のボケ）が発生しないことをログ・`scripts/calibrate.py`のプレビューで確認
2. USBカメラのデバイス番号の安定性
3. ラズパイ5実機での `/dev/gpiochip*` アクセス権限・lgpio動作
4. **絶縁モジュールの結線・極性確認**: 出力側がPLCの24V入力回路を正しく開閉できること、
   入力側がPLCのNPNシンク出力を正しく検出しラズパイのGPIOに安全な3.3V/5Vレベルで
   伝わること。`active_high`/`pull_up`の設定がモジュールの実際の出力極性と一致していること
5. 実際の照明・ライン外観に基づく検知方式・しきい値の選定、複数枚基準フレームの取得
6. 物理リセットボタン・PLCリセット信号それぞれ単独での復帰動作確認
7. PLCラダーロジック経由でのパトライト黄色点灯・消灯・点滅パススルーの実機確認
8. カメラ切断時にアラーム出力がチャタリングしないこと、カメラ異常検知が動作すること
9. systemdの自動起動・自動再起動・watchdogによるハング検知の実機確認
10. 実運用（昼夜・照明条件が変わる時間帯を含む）でのログ確認によるしきい値の妥当性検証
11. 絶縁モジュールのロジックレベル（3.3V基準か）の確認、必要ならバッファ段の追加
12. カメラ位置ズレ／異常検知が実際の振動・照明変化下で誤検知しないことの確認
13. 実写での定量的な受け入れ基準（誤検知率・未検知率・検知〜PLC出力遅延）の測定と記録
14. サージ・ノイズ対策（TVS/バリスタ、シールド配線、動力線との分離、ヒューズ/PTC）の配線確認
15. キャップ投入中の点滅検知が実際の補充動作で適切に動作し、通常の振動等で誤動作しないこと
16. Wi-Fi監視機能: 工場内での電波到達範囲・強度、複数端末同時接続時の負荷、検知ループへの影響

## テスト

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

実機（カメラ・GPIO・PLC）なしで実行できる範囲をカバーしています。GPIOは`gpiozero`の
`MockFactory`、カメラ・映像処理は合成画像で検証しています。
