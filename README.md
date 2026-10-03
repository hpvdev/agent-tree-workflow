# Agent Tree Workflow

Bộ workflow Codex cài riêng cho từng project: agent chính điều phối, các agent chuyên trách xử lý phần việc phù hợp, reviewer hỗ trợ tại các mốc cần thiết. Có cấu hình model theo vai trò và bảng tiến trình terminal lấy từ sự kiện Codex thực tế.

Không sửa `~/.codex/config.toml`, `~/.codex/AGENTS.md` hay cấu hình project khác. Thư mục bộ cài không tự kích hoạt workflow. Đây là workflow hướng dẫn Codex phân công theo ngữ cảnh, không phải một scheduler bắt buộc chạy đủ mọi agent trong mọi task.

## Yêu cầu

- Python 3.9 trở lên; không cần `pip install` hay thư viện ngoài.
- Codex CLI đã cài, đăng nhập, hỗ trợ `agents.enabled`, `agents.max_concurrent_threads_per_session` và `codex exec --json`.
- Tài khoản có quyền dùng các model bạn chọn. Mặc định là GPT-6 Sol, Luna, Astra; có thể đổi toàn bộ.
- Jev là tùy chọn. Không có Jev thì agent chính tự giải quyết quyết định ngữ nghĩa.

## Cài từ thư mục bộ cài

Thay `/path/to/project` bằng đường dẫn project thật đã tồn tại:

```sh
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
```

Bộ cài chỉ thêm các file sau và giữ nguyên cấu hình Codex hiện có:

```text
project/
├── AGENTS.md                         # thêm một khối có đánh dấu
├── .codex/agents/
│   ├── agent_tree_worker.toml
│   ├── agent_tree_explorer.toml
│   ├── agent_tree_researcher.toml
│   └── agent_tree_astra.toml
└── .agent-tree/
    ├── settings.json                # model, reasoning effort, số agent
    ├── run.py                       # mở Codex hoặc chạy bảng tiến trình
    ├── monitor.py
    ├── install.py                   # đổi cấu hình và gỡ bản cài
    ├── manifest.json                # kiểm tra file trước khi ghi/gỡ
    └── logs/                        # sinh ra khi dùng --watch, không đưa vào Git
```

Không ghi đè file trùng tên hay ghi qua symbolic link. Cài lại với cùng cấu hình không chèn lặp hướng dẫn. Repo được chọn cần cho phép Codex đọc chỉ dẫn project; các quy định quản trị hoặc chỉ dẫn ưu tiên cao hơn vẫn có hiệu lực.

## Cài từ Git

Repository: https://github.com/hpvdev/agent-tree-workflow

Clone bộ cài rồi chỉ định project muốn dùng:

```sh
git clone https://github.com/hpvdev/agent-tree-workflow.git ~/Documents/Agent-Tree-Workflow
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
```

Nếu đã có thư mục bộ cài thì dùng thư mục đã clone hoặc chọn một đường dẫn khác, không clone đè lên nó. Không có bước tải rồi chạy script từ internet một cách ngầm định. Có thể checkout một tag hoặc commit cụ thể trước khi cài để dùng đúng phiên bản mong muốn.

## Chạy và xem từng bước

Mở Codex tương tác với model của project:

```sh
cd /path/to/project
python3 .agent-tree/run.py
```

Chạy một yêu cầu với bảng tiến trình trực tiếp:

```sh
python3 .agent-tree/run.py --watch "Triển khai chức năng đã mô tả và kiểm tra phần thay đổi"
```

`--watch` dùng chế độ không tương tác `codex exec --json`. Terminal hiển thị trạng thái lượt chạy, cây agent khi có sự kiện tương ứng, và 12 sự kiện gần nhất: thông báo, lệnh, file thay đổi, gọi công cụ và kết quả. Khi redirect output, chương trình in tuần tự từng dòng để đọc hoặc lưu lại dễ dàng. Ctrl+C dừng tiến trình CLI mà launcher đã mở; kiểm tra trạng thái agent trong Codex nếu dùng backend quản lý phiên độc lập.

Quyền thực thi và sandbox vẫn theo Codex hiện có; workflow không tự bật quyền bỏ qua phê duyệt. Nếu thao tác cần phê duyệt tương tác, dùng chế độ tương tác ở trên. `--watch` không biến yêu cầu cần phê duyệt thành được phép.

Log gốc ở `.agent-tree/logs/*.jsonl`, thông báo CLI ở file `.stderr.log` cùng tên. Xem lại không gọi model:

```sh
python3 .agent-tree/run.py --replay .agent-tree/logs/TEN_FILE.jsonl
```

Xem lệnh sẽ chạy, không mở phiên:

```sh
python3 .agent-tree/run.py --print-command --watch "Kiểm tra phần thay đổi"
```

**Phạm vi hiển thị:** bảng lấy sự kiện do CLI phát ra, không dựng tiến độ giả. Phiên bản CLI không xuất sự kiện agent con thì bảng chỉ hiện các bước của agent chính; không thể xem mọi thao tác nội bộ của agent con từ stream này. Dùng màn hình subagents của Codex hoặc `/agent` trong CLI để xem thêm khi runtime hỗ trợ. Không hiển thị chuỗi suy nghĩ riêng tư, không bịa confidence Jev, chi phí hoặc token từng agent. Log có thể chứa nội dung project và đầu ra lệnh nên được giữ cục bộ, loại khỏi Git bằng `.agent-tree/.gitignore`.

Nếu mở project trực tiếp trong Codex app, khối AGENTS.md và vai trò project vẫn cung cấp workflow khi runtime hỗ trợ; model chính/giới hạn truyền qua launcher và bảng terminal chỉ có khi dùng `run.py`. Đây không phải một widget cài vào ứng dụng Codex.

## Đổi model khi OpenAI cập nhật

Xem cấu hình:

```sh
python3 .agent-tree/install.py show --project .
```

Đổi riêng model và effort của từng vai trò, không cần sửa code hoặc cài lại:

```sh
python3 .agent-tree/install.py configure --project . --main-model MODEL_ID --main-effort high
python3 .agent-tree/install.py configure --project . --worker-model MODEL_ID --worker-effort medium
python3 .agent-tree/install.py configure --project . --explorer-model MODEL_ID --researcher-model MODEL_ID
python3 .agent-tree/install.py configure --project . --astra-model MODEL_ID --astra-effort medium
python3 .agent-tree/install.py configure --project . --max-agents 4
```

Thay `MODEL_ID` bằng ID được tài khoản hỗ trợ; kiểm tra trong bộ chọn model của Codex hoặc `codex debug models` nếu phiên bản CLI có lệnh này. Model ID không bị giới hạn vào danh sách viết sẵn, nên có thể dùng model mới sau này. Effort phải được model đó hỗ trợ. Bộ cài kiểm tra định dạng, không gọi model để kiểm tra quyền truy cập và không tự đổi sang model khác khi lỗi.

Lệnh `configure` đồng bộ settings và TOML vai trò, áp dụng cho phiên chạy tiếp theo. Nên dùng lệnh này thay vì sửa tay các file được quản lý, vì cơ chế gỡ sẽ giữ lại file đã bị chỉnh ngoài bộ cài để tránh mất nội dung của bạn. Cấu hình của project A không đổi model của project B.

## Luồng phối hợp

```text
Yêu cầu
  │
  ▼
Main · Sol/high ── việc nhỏ ──► triển khai trực tiếp
  │
  ├─ thiết kế khó/rủi ro ────► Astra tư vấn, không sửa code
  │
  ├─ quyết định ngữ nghĩa hẹp ► Jev (tùy chọn) → Main đánh giá
  │
  ├─ worker · Sol/medium ────► triển khai phần được giao
  ├─ explorer · Luna/medium ► đọc code và callsite
  └─ researcher · Luna/medium ► đọc tài liệu chính thức
           │
           ▼
Main tích hợp → kiểm tra liên quan → Astra review nếu thay đổi đáng kể
           │
           ▼
Main sửa theo phát hiện có căn cứ → báo kết quả
```

Astra cũng được gọi khi cùng lỗi tồn tại sau hai cách xử lý khác nhau. Mặc định tối đa sáu agent phụ đồng thời; runtime có thể giới hạn thấp hơn. Không nhất thiết gọi đủ các vai trò, agent con không tự tạo thêm agent và worker không sửa chồng file nhau. Model và effort trong settings luôn được ưu tiên so với tên mặc định trong sơ đồ.

## Cập nhật hoặc gỡ

Xem và lưu cấu hình đang dùng trước khi cập nhật:

```sh
python3 /path/to/project/.agent-tree/install.py show --project /path/to/project
git -C ~/Documents/Agent-Tree-Workflow pull --ff-only
python3 /path/to/project/.agent-tree/install.py uninstall --project /path/to/project
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
```

Dùng lại các tùy chọn `--main-model`, `--worker-model`, `--explorer-model`, `--researcher-model`, `--astra-model`, `--*-effort`, `--max-agents` khi cài để giữ lựa chọn riêng. Bộ cài không tự chạy `git pull` hoặc tự cập nhật model.

Chỉ gỡ:

```sh
python3 .agent-tree/install.py uninstall --project .
```

Gỡ đúng khối hướng dẫn và các file do bộ cài quản lý, giữ nguyên nội dung khác được thêm vào AGENTS.md và các log đã lưu. Nếu file quản lý đã bị sửa ngoài lệnh `configure`, lệnh gỡ dừng trước khi xóa để bạn xử lý khác biệt. Giữ thư mục bộ cài trong Documents để cài cho project khác.

## Kiểm tra bộ cài

```sh
python3 -m unittest discover -s tests -v
```

Tests dùng thư mục tạm để kiểm tra cài/gỡ, đổi model, bảo toàn file hiện có và xử lý sự kiện; không gọi model, không thay đổi cấu hình máy. Chạy thật các model cần Codex đã đăng nhập và sẽ sử dụng hạn mức tài khoản.

Tham chiếu: [custom subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [Codex JSONL events](https://learn.chatgpt.com/docs/non-interactive-mode).
