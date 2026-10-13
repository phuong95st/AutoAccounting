/**
 * =========================================================================
 * GOOGLE APPS SCRIPT: TỰ ĐỘNG ĐỒNG BỘ SỔ QUỸ PHÒNG KHÁM NHA KHOA
 * =========================================================================
 * 
 * HƯỚNG DẪN 3 BƯỚC CÀI ĐẶT:
 * 1. Mở file Google Sheets của bạn -> Chọn menu "Tiện ích mở rộng" (Extensions) -> "Apps Script"
 * 2. Xóa hết mã cũ trong khung soạn thảo, copy toàn bộ nội dung file này dán vào và bấm "Lưu" (Ctrl + S)
 * 3. Bấm nút "Triển khai" (Deploy) ở góc trên bên phải -> "Tùy chọn triển khai mới" (New deployment):
 *    - Loại: Chọn "Ứng dụng web" (Web app)
 *    - Mô tả: AutoAccounting Sync
 *    - Thực thi dưới dạng (Execute as): "Tôi" (Me)
 *    - Người có quyền truy cập (Who has access): "Bất kỳ ai" (Anyone)
 *    - Bấm "Triển khai" (Deploy) -> Cấp quyền cho Google Tài khoản -> Copy "URL ứng dụng web"
 * 4. Dán URL đó vào biến GOOGLE_SHEETS_WEBHOOK_URL trong file .env
 */

function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var data = JSON.parse(rawData);
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

    // 2. Chuẩn bị dữ liệu dòng mới
    var isThu = (data.type || "").toLowerCase() === "thu";
    var typeText = isThu ? "THU" : "CHI";
    var methodText = (data.payment_method || "").toLowerCase() === "transfer" ? "Chuyển khoản" : "Tiền mặt";
    var amount = Number(data.amount) || 0;

    var newRow = [
      data.id || (sheet.getLastRow()),
      data.date || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd"),
      data.time || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "HH:mm:ss"),
      typeText,
      amount,
      methodText,
      data.category || "",
      data.description || "",
      data.source || "telegram"
    ];

    sheet.appendRow(newRow);
    var lastRowIdx = sheet.getLastRow();

    // 3. Định dạng màu sắc và kiểu tiền tệ cho dòng vừa thêm
    // Cột Loại (Cột 4)
    var typeCell = sheet.getRange(lastRowIdx, 4);
    typeCell.setFontWeight("bold");
    typeCell.setHorizontalAlignment("center");
    if (isThu) {
      typeCell.setFontColor("#274E13"); // Xanh lá
    } else {
      typeCell.setFontColor("#A61C1C"); // Đỏ cam
    }

    // Cột Số Tiền (Cột 5)
    var amountCell = sheet.getRange(lastRowIdx, 5);
    amountCell.setNumberFormat('#,##0" ₫"');
    amountCell.setFontWeight("bold");
    amountCell.setHorizontalAlignment("right");

    // Canh giữa cho ID, Ngày, Giờ, Hình Thức
    sheet.getRange(lastRowIdx, 1).setHorizontalAlignment("center");
    sheet.getRange(lastRowIdx, 2).setHorizontalAlignment("center");
    sheet.getRange(lastRowIdx, 3).setHorizontalAlignment("center");
    sheet.getRange(lastRowIdx, 6).setHorizontalAlignment("center");

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      row: lastRowIdx
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
