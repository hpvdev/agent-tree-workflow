# Agent Tree Workflow

Bộ workflow Codex cài riêng cho từng project: **Sol lập kế hoạch/viết code → Jev chọn nhánh → tool hoặc agent thực thi → Sol tích hợp/xác minh**. Astra tư vấn trước kế hoạch, khi lỗi lặp lại và trước hoàn tất.

Python 3.9+, thư viện chuẩn, Codex có native subagents/hooks và Jev CLI đã xác thực. Chỉ clone repo chưa cài vào project nào. Bộ cài không sửa cấu hình toàn cục.

## Cài vào project

```sh
git clone https://github.com/hpvdev/agent-tree-workflow.git ~/Documents/Agent-Tree-Workflow
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
```

Thay `/path/to/project` bằng thư mục project có sẵn. Nếu đã clone thì dùng thư mục hiện có.

1. Mở đúng project trong Codex và dùng `/hooks` để xem, chấp thuận các hook Agent Tree theo cơ chế trust của Codex. Hook chưa được trust chưa chạy. Nếu client không có giao diện `/hooks`, dùng Codex CLI hỗ trợ hooks trong project đó để review; không tự chỉnh kho trust bằng script.
2. Bắt đầu phiên mới và gửi yêu cầu. Hook cung cấp RUN_ID riêng cho mỗi lượt; agent làm theo khối workflow đã cài trong `AGENTS.md`.
3. Chọn main model Sol/high trong Codex app. `settings.json` không tự đổi model đang chọn trong app. Cấu hình role xác định model của các agent con; giới hạn runtime và chính sách quản trị vẫn được ưu tiên.
4. Theo dõi lượt làm việc và các agent con ngay trong Codex app; retro được lưu cục bộ sau khi lượt kết thúc.

Bộ cài thêm `.agent-tree/`, `.codex/agents/agent_tree_*.toml`, khối có dấu mốc trong `AGENTS.md`, và **gộp** hook của nó vào `.codex/hooks.json`. Giữ nguyên hook/cấu hình project có sẵn. Refuse file trùng, file đã sửa ngoài bộ cài và symbolic link.

Launcher tùy chọn áp dụng main model/effort, giới hạn agent và approval mode đã cấu hình:

```sh
cd /path/to/project
python3 .agent-tree/run.py "Yêu cầu phát triển của bạn"
```

Launcher và hooks dùng chung journal. Nếu hooks chưa hoạt động, launcher vẫn quan sát CLI/agent bằng adapter, nhưng **không xác nhận được native action đã được Jev chọn**; audit giữ phần đó chưa hoàn tất. Không coi launcher là cách bỏ qua trust.

## Mô hình và vai trò

```text
Astra before_plan ─► Sol/high: lập kế hoạch, viết code
                          │
                     JEV FORK LAYER
                   file / tool / agent / retry
                     ├─ sharp ─► code dispatch
                     └─ split ─► Sol resolve ─► code dispatch
                                           │
                           tool native hoặc agent phù hợp
                           worker / explorer / researcher
                                           │
                                  Sol tích hợp + kiểm tra
                                           │
                                  Astra before_done
                                           │
                                  Sol hoàn tất + audit

Lỗi lặp lại ─► Astra error_repeats ─► Sol áp dụng nhận xét
Quyền thực thi ─► cơ chế approval native của Codex
```

| Vai trò | Model mặc định | Trách nhiệm |
|---|---|---|
| Main | gpt-6-sol / high | Kế hoạch, code, phân công, tích hợp, xác minh |
| Worker | gpt-6-sol / medium | Sửa code và chạy kiểm tra được giao |
| Explorer | gpt-6-luna / medium | Đọc code, tìm file/callsite |
| Researcher | gpt-6-luna / medium | Đọc tài liệu chính thức |
| Astra | gpt-6-astra / medium | Chỉ tư vấn ở ba mốc; không viết code |
| Jev | jev-latest | Chọn nhánh hữu hạn, trả phân phối xác suất |

Ảnh ghi GPT-6.1 Sol; mặc định dùng ID đã cấu hình được ở môi trường triển khai, không giả định mọi tài khoản có cùng model. Tất cả ID/effort đều đổi được. Mặc định tối đa sáu agent con, hoặc giới hạn thấp hơn của runtime. Không bắt buộc tạo đủ ba loại agent cho mọi task. Agent con thực hiện phần được giao, không tự phân công đệ quy.

## Jev là tầng quyết định

Sol chuẩn bị state ngắn và các lựa chọn thực sự có thể thực hiện. Controller gọi `jev ask` thật với câu hỏi Choice. Chỉ state, question và mô tả lựa chọn được gửi tới Jev; không tự upload file, prompt agent, lệnh shell hay toàn bộ hội thoại.

- `which_file`: chọn file cần đọc.
- `which_tool`: chọn thao tác đọc/tìm hoặc tool native cần gọi.
- `which_agent`: chọn worker/explorer/researcher theo công việc; đây là phần mở rộng được người dùng yêu cầu bên cạnh ba dòng fork trong ảnh.
- `retry_or_stop`: chọn thử lại hoặc dừng nhánh, có failure key và giới hạn retry bằng code.

**Sharp:** controller dùng lựa chọn của Jev để dispatch. Đọc/tìm kiếm nội bộ chạy ngay. Với tool/agent native, controller trả lời gọi chính xác, Sol chuyển lời gọi đó sang runtime; hook đối chiếu tool và input trước khi ghi nhận kết quả. Sol không quyết định lại nhánh sharp.

**Split:** không thực thi action. Sol đánh giá bằng chứng rồi `resolve ID CHOICE` hoặc `resolve ID stop`. Lỗi Jev/timeout/schema sai cũng về Sol và ghi rõ nguyên nhân, không tạo xác suất giả.

Ngưỡng ban đầu: confidence ≥ 0.85, xác suất lựa chọn ≥ 0.85, chênh lệch hai lựa chọn đầu ≥ 0.20. Đây là cấu hình kỹ thuật cần hiệu chỉnh theo dữ liệu, không phải hằng số lấy từ ảnh hay bảo đảm đúng. Known facts, việc đã được quyết định và điều phối chờ agent không cần tạo câu hỏi Jev giả.

### Nối lựa chọn với thực thi

Native action đi qua các trạng thái:

```text
pending → awaiting_native → native_running → completed hoặc native_failed
```

Hook chặn tool không khớp khi quyết định còn chờ, và yêu cầu một nhánh `which_agent` trước khi spawn worker/explorer/researcher. Checkpoint Astra, lệnh controller và thao tác chờ vẫn dùng được. Chỉ `PostToolUse` khớp lời gọi đã quan sát mới hoàn tất native action; không có lệnh để Sol tự khai đã chạy. `completed` chứng minh tool đã trả về, không chứng minh code đúng. Test và review vẫn cần thiết.

Input phải đúng tên/shape canonical của runtime: shell hook Codex dùng `Bash` và `input.command`; MCP dùng tên và arguments native. Nếu host không phát hook cho loại tool đó, action còn treo và phải báo giới hạn. Controller Python không có quyền trực tiếp điều khiển tool bên trong phiên Codex; native dispatch vẫn cần lượt gọi tool của main. Vì thế chưa thể khẳng định loại bỏ mọi lượt model hay đạt tốc độ/chi phí trong ảnh.

Workflow này không chặn mọi tool xác định trước, không phải sandbox bảo mật và không thể tự chứng minh agent đã khai báo mọi điểm rẽ ngữ nghĩa. AGENTS quy định điểm nào phải qua Jev; code kiểm tra quyết định đã đăng ký và bằng chứng thực thi. Native approvals vẫn quyết định quyền thực thi, xác suất Jev không cấp quyền.

Ví dụ input/lệnh được cài trong `AGENTS.md`. Dùng `fork --json 'JSON'` với shell quoting chuẩn, lệnh đứng riêng ở project root, để controller có thể xử lý quyết định còn chờ. Args và options lưu cục bộ trong journal; không ghi secrets vào chúng. `non_sensitive=true` là xác nhận của caller, không phải bộ dò bí mật tự động. Nếu không thể mô tả bằng dữ kiện không nhạy cảm, không gửi ra Jev.

## Astra và audit

`before_plan` và `before_done` bắt buộc trong workflow này; `error_repeats` khi lỗi tái diễn. Astra không chạy trên mọi tool call. Controller đối chiếu agent mới, role/model, thời điểm tạo và trạng thái hoàn tất; metadata không đánh giá chất lượng nhận xét.

Trước `before_plan`, xác định đúng tính năng khi tên gọi có thể chỉ nhiều luồng khác nhau. Sol có thể đọc hẹp để phân biệt hoặc hỏi rõ phạm vi; Astra chỉ review mục tiêu đã xác định.

Hooks tự ghi lỗi khi tool response có `isError` hoặc exit code khác 0. Lỗi khác cần Sol báo qua `failure`; không đếm lại một lần lỗi đã ghi. Failure fingerprint tự động dựa trên tool/input giống nhau; nhận ra cùng nguyên nhân qua các lệnh khác nhau vẫn cần Sol. Mỗi lần tái diễn cần Astra mới trước tiếp tục. Retry mặc định tối đa một lần cho cùng failure key.

Fork mới sau review cuối làm hết hiệu lực `before_done`. Sol cũng phải yêu cầu review lại nếu thay đổi liên quan phát sinh ngoài fork. Các lệnh đọc mã thông dụng như `rg`, `nl`, `sed -n` và `git diff` không hủy review đã hoàn tất; lệnh sửa file hoặc lệnh không nhận diện được vẫn hủy để giữ an toàn. Stop hook nhắc hoàn tất một lần; nếu vẫn thiếu, báo audit chưa đạt, không tạo vòng lặp vô hạn hoặc tự đánh dấu đạt. Launcher trả exit 2 khi CLI thành công nhưng workflow chưa đủ.

`--approve-for-me` chỉ áp dụng khi chạy launcher với `approval_mode=auto-review`. Phiên mở trực tiếp trong app dùng quyền native đã chọn; hook không tự bật hoặc phê duyệt thay Codex.

## Nhật ký và retro

Codex app hiển thị hoạt động của phiên và các subagent. Khi một lượt kết thúc, Stop hook tạo retro một lần từ các sự kiện đã ghi; launcher tùy chọn cũng tạo retro khi tiến trình dừng. Bản chi tiết nằm tại `.agent-tree/logs/<run-id>/retro.json`, gồm thời gian, số lượt Astra/Jev, số lần review cuối bị hủy và số sự kiện tool hook. Đây là số liệu điều phối; độ đúng của kết quả cần kiểm tra bằng yêu cầu, kiểm thử và phản hồi thực tế.

Log cục bộ trong `.agent-tree/logs/RUN_ID/events.sqlite3`; index phiên ở `logs/sessions/`. Hook log không giữ raw prompt/tool output. Launcher còn lưu `codex.jsonl`, `timeline.jsonl`, `stderr.log` có thể chứa nội dung task; không chia sẻ nếu chưa kiểm tra. Logs được bỏ qua khi commit Git và giữ lại khi gỡ.

Không có cửa sổ Watch riêng. Nhật ký và retro vẫn được giữ trong project để kiểm tra khi cần.

## Đổi model, cập nhật và gỡ

```sh
python3 .agent-tree/install.py show --project .
python3 .agent-tree/install.py configure --project . --main-model MODEL_ID --main-effort high
python3 .agent-tree/install.py configure --project . --worker-model MODEL_ID --worker-effort medium
python3 .agent-tree/install.py configure --project . --explorer-model MODEL_ID --researcher-model MODEL_ID
python3 .agent-tree/install.py configure --project . --astra-model MODEL_ID --astra-effort high
python3 .agent-tree/install.py configure --project . --jev-model jev-latest
python3 .agent-tree/install.py configure --project . --jev-confidence 0.90 --jev-probability 0.90 --jev-margin 0.25
python3 .agent-tree/install.py configure --project . --max-agents 4
python3 .agent-tree/install.py configure --project . --approval-mode inherit
```

Model/effort phải được tài khoản hỗ trợ. Dùng `configure` để đồng bộ settings, role files và manifest. Áp dụng từ lần chạy tiếp theo; main model trong app vẫn chọn trong app.

```sh
git -C ~/Documents/Agent-Tree-Workflow pull --ff-only
python3 ~/Documents/Agent-Tree-Workflow/install.py upgrade --project /path/to/project
# Gỡ tại project:
python3 .agent-tree/install.py uninstall --project .
```

Dừng các lượt đang chạy trước khi upgrade. Upgrade giữ model/ngưỡng/log; thay đổi định nghĩa hook có thể cần review/trust lại. Gỡ chỉ xóa khối/file/hook thuộc bộ cài, giữ các hook và nội dung khác của project.

## Kiểm chứng và nguồn tham khảo

```sh
python3 -m unittest discover -s tests -v
```

Tests kiểm tra sharp/split, native routing và chống đánh dấu thực thi giả, chọn agent, lỗi lặp, checkpoint, tách lượt/session, cài/gỡ/upgrade và giữ hook có sẵn. Fixtures mô phỏng sự kiện để kiểm tra contract, không phải chứng cứ một client cụ thể đã bật hooks. Muốn xác nhận cài đặt live, cần trust hooks và quan sát một phiên native thực trong project test.

Nguồn chính: [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice), [function calling](https://docs.typesafe.ai/cookbooks/function_calling), [Codex hooks/trust](https://learn.chatgpt.com/docs/hooks), [native subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

Tham khảo cộng đồng: [jev-codex-router](https://github.com/0xNatoshi/jev-codex-router) chọn model/effort mỗi lời gọi. Bộ này giữ vai trò Sol/Astra theo ảnh và tập trung chọn hành động; không cài proxy đó hoặc lấy số tiết kiệm của nó làm kết quả của workflow này. Chưa xác minh được bài gốc trực tiếp của @Bober_smart trên X; ảnh người dùng cung cấp là nguồn yêu cầu bố cục/vai trò.
