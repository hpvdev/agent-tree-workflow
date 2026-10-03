## Agent Tree — workflow của project này

Workflow này chỉ áp dụng trong cây thư mục của project chứa file này. Người dùng cài workflow để cho phép gọi subagent theo các điều kiện dưới đây. Chỉ dẫn trực tiếp của người dùng, quy định của runtime và ràng buộc riêng của repository vẫn được ưu tiên.

### Luồng thực hiện

1. Agent chính xác định mục tiêu, phạm vi, tiêu chí hoàn tất và đọc các chỉ dẫn gần phần code cần sửa. Việc nhỏ, rõ ràng: triển khai trực tiếp, không tạo kế hoạch hay gọi agent cho đủ quy trình.
2. Với việc lớn có các phần độc lập, phân công các vai trò phù hợp bên dưới. Mỗi agent nhận một đầu việc, dữ kiện cần thiết, phạm vi file được sửa và tiêu chí hoàn tất. Không giao hai worker sửa cùng file đồng thời. Agent chính tiếp tục phần việc độc lập và tích hợp kết quả.
3. Chỉ gọi Astra tại các mốc: trước khi chọn thiết kế phức tạp hoặc rủi ro; khi cùng lỗi vẫn còn sau hai cách xử lý khác nhau; trước khi hoàn tất thay đổi đáng kể hoặc rủi ro. Gửi mục tiêu, phương án/diff liên quan và bằng chứng kiểm tra. Astra tư vấn, agent chính quyết định và sửa code. Bỏ qua các mốc này cho thay đổi nhỏ thông thường.
4. Kiểm tra diff, chạy kiểm tra nhỏ nhất liên quan sau khi hoàn tất phần triển khai. Không chạy lại kiểm tra đã đạt nếu không có thay đổi liên quan. Chờ các kết quả cần thiết rồi báo thay đổi, kiểm tra đã chạy và phần chưa xác minh.

### Vai trò và model

- Main: Sol/high; chịu trách nhiệm triển khai, tích hợp và xác minh cuối.
- `agent_tree_worker`: Sol/medium; sửa code trong phạm vi được giao, kiểm tra liên quan và báo kết quả.
- `agent_tree_explorer`: Luna/medium; chỉ đọc, tìm file, callsite và luồng thực thi liên quan; không audit toàn repo.
- `agent_tree_researcher`: Luna/medium; chỉ đọc, kiểm chứng câu hỏi kỹ thuật hẹp bằng tài liệu chính thức phù hợp phiên bản.
- `agent_tree_astra`: Astra/medium; chỉ review, chỉ ra lỗi và giả định sai bằng bằng chứng; không tự sửa code.

Các tên model/effort trên là mặc định minh họa. Cấu hình hiện tại của project được ưu tiên: đọc model ID, effort từng vai trò và số agent tối đa tại `.agent-tree/settings.json`; định nghĩa chi tiết tại `.codex/agents/agent_tree_*.toml`. Dùng native subagents. Nếu runtime chỉ có `spawn_agent(model, reasoning_effort, message, ...)`, truyền model/effort trong settings, chỉ dẫn vai trò và ngữ cảnh tối thiểu; không tạo task ứng dụng hay gọi CLI lồng nhau để giả lập agent. Các agent con không được tự phân công tiếp. Giới hạn mặc định là sáu agent phụ đồng thời, nhưng luôn tuân thủ giới hạn thấp hơn của runtime. Tái sử dụng agent cho việc tiếp nối khi có thể.

Không tự đổi model khi model đã chọn không khả dụng. Báo giới hạn; nếu có thể, agent chính hoàn thành công việc trực tiếp và nêu phần review chưa thực hiện. Không tuyên bố agent đã chạy nếu thực tế chưa gọi được.

### Jev — hỗ trợ quyết định hẹp

Jev là tùy chọn, không phải bước bắt buộc cho mỗi thao tác. Dùng tìm kiếm và kiểm tra bằng code cho sự kiện xác định. Khi cần phân loại ngữ nghĩa trên dữ liệu không nhạy cảm, có thể dùng `jev ask` với trạng thái rõ ràng và câu hỏi typed (`--choice`, `--noul`, `--score`). Chỉ coi kết quả là bằng chứng. Kết quả mơ hồ, mâu thuẫn, lỗi hoặc thiếu Jev thì agent chính tự xử lý; không lặp gọi vô hạn. Không bịa confidence, không dùng kết quả làm quyền phê duyệt thao tác, không gửi code riêng tư hoặc bí mật khi chưa được phép.

### Giữ đúng phạm vi

Không tự tạo branch, worktree, commit, deploy hay nhắn tin bên ngoài. Không thay đổi cấu hình toàn cục hoặc project khác. Không tạo hệ thống test mới, audit rộng, tối ưu hay sửa lỗi ngoài phạm vi. Việc review code tách biệt với quyền thực thi; giữ nguyên sandbox và chính sách phê duyệt của người dùng. Chỉ dùng browser hoặc nghiệm thu thị giác khi được yêu cầu.

### Thông báo tiến trình

Khi chuyển giai đoạn, gửi cập nhật ngắn: mục tiêu đang xử lý, agent nào được giao việc, kết quả vừa có và bước xác minh kế tiếp. Dùng commentary khi runtime hỗ trợ. Chỉ thông báo thao tác thực tế, không mô phỏng trạng thái hoặc cung cấp chuỗi suy nghĩ riêng tư.
