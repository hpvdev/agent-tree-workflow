# Agent Tree Workflow

Workflow Codex cài riêng cho từng project, triển khai các tầng trong mô hình tham chiếu: **Sol điều phối → Jev xử lý điểm rẽ → các agent chuyên trách → Sol xác minh**, với **Astra tư vấn ở ba mốc** và bảng theo dõi dữ liệu thực.

Không chỉnh cấu hình toàn cục. Không tự cài vào project khi chỉ clone repo. Python 3.9+, thư viện chuẩn; cần Codex CLI đã đăng nhập và `jev` đã cấu hình xác thực. Jev thiếu hoặc lỗi sẽ chuyển quyết định về Sol và ghi rõ fallback.

## Cài và chạy

```sh
git clone https://github.com/hpvdev/agent-tree-workflow.git ~/Documents/Agent-Tree-Workflow
python3 ~/Documents/Agent-Tree-Workflow/install.py install --project /path/to/project
cd /path/to/project
python3 .agent-tree/run.py --watch "Yêu cầu phát triển của bạn"
```

Thay `/path/to/project` bằng project đã tồn tại. Nếu đã clone thì dùng thư mục hiện có. `--watch` có thể bỏ qua: bản v2 luôn chạy launcher có theo dõi/audit. Không tự mở phiên tương tác khi thiếu yêu cầu.

Bộ cài thêm một khối đánh dấu vào `AGENTS.md`, vai trò vào `.codex/agents/agent_tree_*.toml`, và chương trình vào `.agent-tree/`. Không ghi đè cấu hình Codex của project, file trùng tên hoặc symbolic link. Repo cần được Codex tin cậy theo cơ chế của Codex; quyền quản trị và chỉ dẫn ưu tiên cao hơn vẫn áp dụng.

## Cơ chế hoạt động

```text
                 Astra · on call · chỉ tư vấn
                  ↑       ↑          ↑
             before_plan lỗi lặp   before_done
                  │       │          │
Sol/high ──► kế hoạch ──► Jev fork layer
                           ├─ sharp ─► Python thực hiện nhánh đã khai báo
                           └─ split ─► Sol quyết định ─► Python thực hiện
                                          │
                          worker / explorer / researcher
                                          │
                               Sol review + kiểm tra
                                          │
                               Astra before_done
                                          │
                               kiểm toán workflow
```

| Vai trò | Mặc định | Công việc |
|---|---|---|
| Main | GPT-6 Sol / high | Kế hoạch, phân công, tích hợp, review, xác minh |
| Worker | GPT-6 Sol / medium | Sửa code và chạy kiểm tra được giao |
| Explorer | GPT-6 Luna / medium | Đọc code, tìm file/callsite |
| Researcher | GPT-6 Luna / medium | Tra tài liệu chính thức |
| Astra | GPT-6 Astra / medium | Tư vấn trước plan, khi lỗi lặp, trước hoàn tất; không viết code |
| Jev | jev-latest | Trả lựa chọn có kiểu và phân phối xác suất |

Model chỉ là mặc định có thể đổi. Ảnh dùng GPT-6.1 Sol; bộ cài không tự giả định tài khoản có model đó. Chọn ID bạn được phép dùng. Tối đa sáu agent phụ đồng thời, tuân thủ giới hạn thấp hơn của runtime. Agent con không tự phân công tiếp.

**Đây là native subagents của Codex**, không phải nhiều CLI giả vai trò. Sol thực hiện các bước theo chỉ dẫn; controller kiểm tra các điểm rẽ và điều kiện hoàn tất. Controller không chặn mọi lời gọi tool của Sol: audit thất bại phát hiện bước thiếu, không hoàn tác code đã sửa. Quyền thực thi vẫn thuộc Codex, không thuộc xác suất Jev.

## Jev thực thi như thế nào?

Tầng `control.py fork` nhận một câu hỏi hẹp, state không nhạy cảm và danh sách lựa chọn hữu hạn. Nó gọi **Jev CLI thật**, kiểm tra phân phối rồi phân nhánh:

- **Sharp:** lựa chọn không phải fallback, confidence ≥ 0.85, xác suất lựa chọn ≥ 0.85 và chênh lệch với lựa chọn thứ hai ≥ 0.20. Python chạy action tương ứng ngay, ghi sự kiện và trả kết quả.
- **Split:** Sol nhận quyết định chưa rõ, xác suất gốc nếu có và ID quyết định. Chưa có action nào chạy. Sol dùng bằng chứng để `resolve ID CHOICE`, hoặc `resolve ID stop`.
- **Lỗi Jev:** thiếu CLI/xác thực, timeout hoặc đầu ra sai → split về Sol; không tạo confidence giả.

Các ngưỡng trên là **chính sách kỹ thuật ban đầu**, không phải số được suy ra từ ảnh hoặc bảo đảm độ đúng. Có thể điều chỉnh theo dữ liệu thật. Không đồng nhất `confidence` với xác suất lựa chọn; nhật ký giữ cả hai.

Ba loại fork: `which_file`, `which_tool`, `retry_or_stop`. Action tự động hiện gồm **đọc file, tìm chuỗi trong file và dừng nhánh hiện tại**. Chúng có giới hạn kích thước và chỉ đọc trong project. Retry lặp lại một action đọc/tìm đã khai báo, mặc định tối đa một lần cho cùng failure key; lỗi tái diễn cần checkpoint Astra mới. Edits, shell, tests và network vẫn qua native tools/approval của Codex. Không có cơ chế cho Jev tự phê duyệt một lệnh shell bất kỳ.

Chỉ state, question và mô tả lựa chọn được gửi ra Jev. Code không tự tải nội dung file lên Jev. Paths/action giữ cục bộ, trừ khi người tạo câu hỏi đưa chúng vào mô tả. Agent phải kiểm tra dữ liệu không nhạy cảm trước khi đặt `non_sensitive=true`; đây là xác nhận của caller, không phải bộ phát hiện bí mật tự động.

Định dạng input và các lệnh controller được cài trực tiếp vào khối workflow trong `AGENTS.md`. Không cần tự nhập lệnh fork trong sử dụng thông thường: Sol gọi controller tại các điểm rẽ phù hợp. Không ép Jev xử lý mọi sự kiện xác định hoặc bịa câu hỏi để tăng số fork.

## Astra và điều kiện hoàn tất

Controller ghi checkpoint pending; Sol tạo **một Astra mới** cho mốc đó, đợi phản hồi và đưa ID thật để hoàn tất. Observer đối chiếu role, model và trạng thái đã hoàn tất của agent mới sau checkpoint. Không chấp nhận agent giả, sai model, còn chạy hoặc lấy lại review cũ.

- `before_plan`: bắt buộc trước lập kế hoạch.
- `error_repeats`: khi cùng failure fingerprint được báo lại, không phải sau một số cách sửa tùy ý. Việc nhận diện lỗi và gọi `failure` do Sol thực hiện, nhật ký ghi rõ nguồn `agent_report`.
- `before_done`: bắt buộc sau triển khai/xác minh. Nếu sửa code liên quan sau review, Sol cần review mới.

Cuối phiên, code kiểm tra checkpoint và quyết định còn treo. Codex kết thúc lượt thành công nhưng thiếu bước thì launcher trả **exit 2**, không tuyên bố workflow đạt. Việc phát hiện chất lượng review hay tính đúng đắn của code vẫn cần Sol/Astra và test; metadata chỉ chứng minh lời gọi có xảy ra và hoàn tất.

## Auto review cho quyền thực thi

Mặc định launcher truyền `--approve-for-me` cho Codex: dùng sandbox workspace-write và cơ chế xét duyệt tự động native. Đây là tầng kiểm tra quyền tool, tách biệt với review code của Astra và audit workflow. Chương trình không tự cấp quyền, không bỏ qua sandbox, không tự trả lời thay bộ xét duyệt. Thao tác bị từ chối vẫn phải xử lý theo kết quả của Codex.

Có thể dùng lại quyền hiện có của Codex cho project này bằng:

```sh
python3 .agent-tree/install.py configure --project . --approval-mode inherit
```

Đặt lại `--approval-mode auto-review` để theo mô hình. Chính sách quản trị hoặc runtime cao hơn vẫn được ưu tiên.

## Xem luồng chạy

Terminal tương tác hiển thị:

- Main, cây vai trò agent, model thực tế và trạng thái đọc từ metadata.
- Số fork Jev, sharp/split, xác suất và confidence thật.
- Các checkpoint Astra, số lần gọi và input tokens quan sát được.
- Nhật ký các bước gần nhất, lệnh, file, kết quả kiểm tra.

`codex exec --json` cung cấp hoạt động main. Adapter bổ sung metadata từ rollout cục bộ **chỉ của root session này và hậu duệ**, không giải mã nội dung mã hóa. Định dạng rollout là chi tiết nội bộ có thể đổi theo Codex; nếu không quan sát được thì không xác nhận checkpoint và workflow báo thiếu dữ kiện. Đây không phải giao diện tự vẽ trạng thái giả hay một widget cài vào Codex app.

Log mỗi lượt nằm trong `.agent-tree/logs/RUN_ID/`:

| File | Nội dung |
|---|---|
| `codex.jsonl` | Stream gốc từ CLI |
| `timeline.jsonl` | Stream CLI và sự kiện Jev/agent/checkpoint theo thứ tự quan sát |
| `events.sqlite3` | Nhật ký quyết định, checkpoint và metadata |
| `stderr.log` | Chẩn đoán CLI |

Xem lại (không gọi model):

```sh
python3 .agent-tree/run.py --replay .agent-tree/logs/RUN_ID
```

Khi redirect stdout thì in nhật ký từng dòng, không xóa màn hình. Ctrl+C dừng CLI đã mở; Codex có thể quản lý agent độc lập nên kiểm tra subagents nếu cần dừng toàn bộ. Log được loại khỏi Git và giữ lại khi gỡ. Không hiển thị chuỗi suy nghĩ riêng tư, không bịa token/giá. Input tokens là số Codex báo, không phải số byte file đã đọc hay chi phí thanh toán.

Nếu mở trực tiếp bằng Codex app, chỉ dẫn/role project vẫn có thể được nạp nhưng controller đầy đủ cần launcher. Không tự mở CLI lồng trong agent để che giấu sự thiếu khả năng.

## Đổi model và ngưỡng

```sh
python3 .agent-tree/install.py show --project .
python3 .agent-tree/install.py configure --project . --main-model MODEL_ID --main-effort high
python3 .agent-tree/install.py configure --project . --worker-model MODEL_ID --worker-effort medium
python3 .agent-tree/install.py configure --project . --explorer-model MODEL_ID --researcher-model MODEL_ID
python3 .agent-tree/install.py configure --project . --astra-model MODEL_ID
python3 .agent-tree/install.py configure --project . --jev-model jev-latest
python3 .agent-tree/install.py configure --project . --jev-confidence 0.90 --jev-probability 0.90 --jev-margin 0.25
python3 .agent-tree/install.py configure --project . --max-agents 4
```

Model ID không bị khóa vào danh sách cứng. Effort phải được model hỗ trợ. Dùng `codex debug models` nếu CLI hỗ trợ để xem model tài khoản; `jev models` cho Jev. Thay đổi áp dụng từ lần chạy tiếp theo, không tự đổi model khi lỗi. Dùng `configure` để đồng bộ settings, role files và manifest, không sửa tay các file được quản lý.

## Cập nhật và gỡ

```sh
git -C ~/Documents/Agent-Tree-Workflow pull --ff-only
python3 ~/Documents/Agent-Tree-Workflow/install.py upgrade --project /path/to/project
```

Upgrade giữ lựa chọn model/effort/ngưỡng và log cũ. Dừng các lượt đang chạy trước khi upgrade. File đã bị sửa ngoài bộ cài thì lệnh dừng để tránh ghi đè.

```sh
python3 .agent-tree/install.py uninstall --project .
```

Gỡ đúng khối workflow và các file quản lý; giữ nội dung khác của AGENTS.md và log. Cấu hình toàn cục và project khác không đổi.

## Kiểm chứng

```sh
python3 -m unittest discover -s tests -v
```

Tests kiểm tra cài/gỡ, chọn model, sharp/split, lỗi Jev, retry budget, ranh giới project, chống chạy lặp action và chứng cứ Astra. Không gọi API trong unit tests. Smoke test thực dùng project riêng và tiêu thụ hạn mức Codex/Jev.

Tham chiếu: [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [CLI events](https://learn.chatgpt.com/docs/non-interactive-mode), [lưu ý định dạng transcript](https://learn.chatgpt.com/docs/hooks), [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice), [confidence](https://docs.typesafe.ai/confidence), [function dispatch](https://docs.typesafe.ai/cookbooks/function_calling).
