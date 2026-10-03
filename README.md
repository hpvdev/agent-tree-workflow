# Agent Tree Workflow

Agent Tree là một **Codex skill gọi khi cần** cho từng project. Các phiên Codex thường không chạy quy trình này và không gọi Jev, Astra hay hook Agent Tree. Khi người dùng gọi `$agent-tree`, Sol điều phối; Astra tư vấn ở các mốc; **Jev chọn agent thực hiện trước khi Sol bắt đầu phần việc chính**.

## Cài vào project

Yêu cầu Python 3.9+, Jev CLI đã xác thực và Codex có native subagents. Clone repo một lần rồi cài vào project cần dùng:

```sh
git clone https://github.com/hpvdev/agent-tree-workflow.git ~/Documents/Agent-Tree-Workflow
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
```

Bộ cài thêm `.codex/skills/agent-tree/`, `.codex/agents/agent_tree_*.toml` và `.agent-tree/` trong project. Nó **không sửa `AGENTS.md`, không đăng ký `.codex/hooks.json` và không sửa cấu hình Codex toàn cục**. Skill đặt `allow_implicit_invocation: false`, nên chỉ được dùng khi bạn gọi rõ tên. Mở lại project hoặc tạo lượt mới nếu Codex chưa thấy skill vừa cài.

Trong Codex app, nhập:

```text
Dùng $agent-tree để thực hiện yêu cầu này trong project.
```

Bạn cũng có thể chọn Agent Tree từ danh sách skill trong app rồi viết yêu cầu cụ thể. Những lượt không gọi skill vẫn chạy theo quy tắc Codex/project bình thường.

## Luồng khi gọi skill

```text
Yêu cầu + $agent-tree
       ↓
Astra before_plan → Sol xác định phạm vi
       ↓
Jev which_agent → Sol/main hoặc Worker/Explorer/Researcher
       ↓
Agent được chọn làm phần việc; Sol điều phối và tích hợp
       ↓
Jev chọn tiếp khi có nhánh file/tool/retry thực sự
       ↓
Sol kiểm tra → Astra before_done → audit + retro
```

Jev luôn được hỏi để chọn người thực hiện **đầu lượt**. Sol là một lựa chọn hợp lệ, nhưng chỉ làm trực tiếp khi Jev chọn Sol. Với lựa chọn agent con, controller trả lời gọi native, Codex spawn agent và controller đối chiếu agent quan sát được trước khi tính nhánh hoàn tất. Nếu Jev thiếu bằng chứng, lỗi hoặc không chọn được, Sol bổ sung thông tin hẹp rồi hỏi lại; Sol không tự chọn agent thay Jev. Astra được gọi trước kế hoạch, trước hoàn tất và khi lỗi lặp lại; không gọi ở mọi tool.

Quy trình skill không cài hook. Nó dùng `CODEX_THREAD_ID` và metadata cục bộ để kiểm tra role, model, quan hệ cha/con và checkpoint. Nếu Codex không cung cấp các dữ kiện này, skill phải báo phần chưa kiểm chứng. Không có hook nên controller không thể chứng minh chính xác mọi input/output của native tool; quyền thực thi vẫn do Codex quản lý. Retro trong `.agent-tree/logs/RUN_ID/retro.json` đo điều phối, không đo chất lượng code. Nhật ký ở cùng thư mục, được bỏ qua khi commit Git.

## Vai trò và model mặc định

| Vai trò | Model | Trách nhiệm |
|---|---|---|
| Sol/main | `gpt-6-sol` / high | Điều phối, lập kế hoạch, tích hợp; trực tiếp thực hiện nếu Jev chọn |
| Worker | `gpt-6-sol` / medium | Sửa code trong phạm vi được giao |
| Explorer | `gpt-6-luna` / medium | Đọc code, tìm file/callsite |
| Researcher | `gpt-6-luna` / medium | Tra tài liệu |
| Astra | `gpt-6-astra` / medium | Tư vấn theo checkpoint, không sửa code |
| Jev | `jev-latest` | Chọn agent và các nhánh ngữ nghĩa hữu hạn |

Model ID và effort đều có thể đổi. Model main đang chọn trong Codex app không tự đổi theo `settings.json`; cấu hình project áp dụng cho role agent và Jev. Ví dụ:

```sh
python3 .agent-tree/install.py configure --project . --worker-model MODEL_ID --worker-effort high
python3 .agent-tree/install.py configure --project . --astra-model MODEL_ID
python3 .agent-tree/install.py configure --project . --jev-model MODEL_ID
python3 .agent-tree/install.py configure --project . --max-agents 4
```

## Cập nhật hoặc gỡ

```sh
git -C ~/Documents/Agent-Tree-Workflow pull --ff-only
python3 ~/Documents/Agent-Tree-Workflow/install.py upgrade --project /path/to/project
python3 /path/to/project/.agent-tree/install.py uninstall --project /path/to/project
```

Dừng lượt Agent Tree đang chạy trước khi nâng cấp. Upgrade từ bản hook cũ gỡ khối Agent Tree trong `AGENTS.md`, nhóm hook Agent Tree và Watch cũ; giữ nội dung project khác, model đã cấu hình và log. Các hook của project không thuộc Agent Tree vẫn được giữ.

Kiểm thử bộ cài và controller:

```sh
python3 -m unittest discover -s tests
```

Chi tiết lệnh controller và cấu trúc lựa chọn Jev nằm trong [workflow reference](templates/workflow.md). Cách đóng gói và gọi skill dựa trên [tài liệu OpenAI về Codex skill](https://developers.openai.com/plugins/build/skills).
