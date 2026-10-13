/**
 * =========================================================================
 * GOOGLE APPS SCRIPT: TỰ ĐỘNG ĐỒNG BỘ SỔ QUỸ PHÒNG KHÁM NHA KHOA
 * =========================================================================
 * 
 * HƯỚNG DẪN CÀI ĐẶT:
 * 1. Mở file Google Sheets -> Chọn menu "Tiện ích mở rộng" (Extensions) -> "Apps Script"
 * 2. Xóa hết mã cũ trong khung soạn thảo, copy toàn bộ nội dung file này dán vào và bấm "Lưu" (Ctrl + S)
 * 3. Bấm nút "Triển khai" (Deploy) ở góc trên bên phải -> "Tùy chọn triển khai mới" (New deployment):
 *    - Loại: Chọn "Ứng dụng web" (Web app)
 *    - Mô tả: AutoAccounting Sync
 *    - Thực thi dưới dạng (Execute as): "Tôi" (Me)
 *    - Người có quyền truy cập (Who has access): "Bất kỳ ai" (Anyone)
 *    - Bấm "Triển khai" -> Bấm "Nâng cao" (Advanced) -> "Đi tới [Tên dự án] (không an toàn)" -> Bấm "Cho phép" (Allow)
 * 4. Copy chuỗi "URL ứng dụng web" dán vào biến GOOGLE_SHEETS_WEBHOOK_URL trong file .env
 */

function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var payload = JSON.parse(rawData);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getActiveSheet();

    // 1. Khởi tạo tiêu đề nếu trang tính còn trống
    if (sheet.getLastRow() === 0) {
      var headers = [
        "ID", "Ngày", "Giờ", "Loại", "Số Tiền", 
        "Hình Thức", "Danh Mục", "Nội Dung", "Nguồn Ghi"
      ];
      sheet.appendRow(headers);
      
      // Định dạng dòng tiêu đề
      var headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setBackground("#1F497D");
      headerRange.setFontColor("#FFFFFF");
      headerRange.setFontWeight("bold");
      headerRange.setHorizontalAlignment("center");
      sheet.setFrozenRows(1);
    }

    // 2. Chuẩn bị dữ liệu (Hỗ trợ cả 1 giao dịch lẻ hoặc mảng nhiều giao dịch sao kê)
    var items = Array.isArray(payload) ? payload : [payload];
    var startRow = sheet.getLastRow() + 1;
    var rowsToAdd = [];

    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var isThu = (it.type || "").toLowerCase() === "thu";
      var typeText = isThu ? "THU" : "CHI";
      var methodText = (it.payment_method || "").toLowerCase() === "transfer" ? "Chuyển khoản" : "Tiền mặt";
      var amount = Number(it.amount) || 0;

      rowsToAdd.push([
        it.id || (startRow + i - 1),
        it.date || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd"),
        it.time || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "HH:mm:ss"),
        typeText,
        amount,
        methodText,
        it.category || "",
        it.description || "",
        it.source || "telegram"
      ]);
    }

    if (rowsToAdd.length > 0) {
      var numRows = rowsToAdd.length;
      var range = sheet.getRange(startRow, 1, numRows, 9);
      range.setValues(rowsToAdd);

      // Định dạng màu sắc và tiền tệ cho các dòng vừa thêm
      for (var r = 0; r < numRows; r++) {
        var currRowIdx = startRow + r;
        var isThuRow = rowsToAdd[r][3] === "THU";
        
        // Cột Loại (Cột 4)
        var typeCell = sheet.getRange(currRowIdx, 4);
        typeCell.setFontWeight("bold");
        typeCell.setHorizontalAlignment("center");
        typeCell.setFontColor(isThuRow ? "#274E13" : "#A61C1C");

        // Cột Số Tiền (Cột 5)
        var amountCell = sheet.getRange(currRowIdx, 5);
        amountCell.setNumberFormat('#,##0" ₫"');
        amountCell.setFontWeight("bold");
        amountCell.setHorizontalAlignment("right");

        // Canh giữa cho ID, Ngày, Giờ, Hình thức
        sheet.getRange(currRowIdx, 1).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 2).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 3).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 6).setHorizontalAlignment("center");
      }
    }

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      count: rowsToAdd.length
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput("Google Sheets Webhook cho AutoAccounting đang hoạt động bình thường!");
}
