/**
 * =========================================================================
 * GOOGLE APPS SCRIPT: HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU SỔ QUỸ TRÊN GOOGLE SHEETS
 * =========================================================================
 * 
 * HƯỚNG DẪN CẬP NHẬT:
 * 1. Mở file Google Sheets -> Chọn menu "Tiện ích mở rộng" (Extensions) -> "Apps Script"
 * 2. Thay thế toàn bộ mã bằng nội dung file này và bấm "Lưu" (Ctrl + S)
 * 3. Bấm "Triển khai" (Deploy) -> "Quản lý bản triển khai" (Manage deployments)
 *    -> Bấm biểu tượng cây bút (Chỉnh sửa) -> Chọn Phiên bản (Version): "Mới" (New) -> Bấm "Triển khai" (Deploy).
 */

function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var payload = JSON.parse(rawData);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getActiveSheet();

    initHeaderIfNeeded(sheet);

    // ==========================================
    // 1. XỬ LÝ LỆNH XÓA (DELETE)
    // ==========================================
    if (payload.action === "delete") {
      var targetId = Number(payload.id);
      var lastRow = sheet.getLastRow();
      if (lastRow <= 1) {
        return jsonResponse({ status: "error", message: "Bảng tính trống" });
      }

      var idRange = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
      for (var i = idRange.length - 1; i >= 0; i--) {
        if (Number(idRange[i][0]) === targetId) {
          sheet.deleteRow(i + 2);
          return jsonResponse({ status: "success", deleted_id: targetId });
        }
      }
      return jsonResponse({ status: "not_found", message: "Không tìm thấy ID" });
    }

    // ==========================================
    // 2. XỬ LÝ LỆNH THÊM GIAO DỊCH (ADD)
    // ==========================================
    var items = [];
    if (payload.action === "add" && payload.data) {
      items = Array.isArray(payload.data) ? payload.data : [payload.data];
    } else if (Array.isArray(payload)) {
      items = payload;
    } else {
      items = [payload];
    }

    var startRow = sheet.getLastRow() + 1;
    var rowsToAdd = [];

    for (var j = 0; j < items.length; j++) {
      var it = items[j];
      var isThu = (it.type || "").toLowerCase() === "thu";
      var typeText = isThu ? "THU" : "CHI";
      var methodText = (it.payment_method || "").toLowerCase() === "transfer" ? "Chuyển khoản" : "Tiền mặt";
      var amount = Number(it.amount) || 0;

      rowsToAdd.push([
        it.id || (startRow + j - 1),
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

      // Định dạng màu sắc và tiền tệ
      for (var r = 0; r < numRows; r++) {
        var currRowIdx = startRow + r;
        var isThuRow = rowsToAdd[r][3] === "THU";
        
        var typeCell = sheet.getRange(currRowIdx, 4);
        typeCell.setFontWeight("bold");
        typeCell.setHorizontalAlignment("center");
        typeCell.setFontColor(isThuRow ? "#274E13" : "#A61C1C");

        var amountCell = sheet.getRange(currRowIdx, 5);
        amountCell.setNumberFormat('#,##0" ₫"');
        amountCell.setFontWeight("bold");
        amountCell.setHorizontalAlignment("right");

        sheet.getRange(currRowIdx, 1).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 2).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 3).setHorizontalAlignment("center");
        sheet.getRange(currRowIdx, 6).setHorizontalAlignment("center");
      }
    }

    var firstId = rowsToAdd.length > 0 ? rowsToAdd[0][0] : null;
    return jsonResponse({ status: "success", count: rowsToAdd.length, id: firstId });


  } catch (err) {
    return jsonResponse({ status: "error", message: err.toString() });
  }
}

function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getActiveSheet();
    var action = (e && e.parameter && e.parameter.action) ? e.parameter.action : "ping";

    if (action === "ping") {
      return jsonResponse({ status: "ok", message: "Google Sheets DB Online" });
    }

    var lastRow = sheet.getLastRow();
    if (lastRow <= 1) {
      return jsonResponse({
        status: "empty",
        total_thu: 0, total_chi: 0, balance: 0, count: 0, items: []
      });
    }

    var rows = sheet.getRange(2, 1, lastRow - 1, 9).getValues();

    // ==========================================
    // 3. TRUY VẤN TỔNG KẾT HÔM NAY (TODAY)
    // ==========================================
    if (action === "today") {
      var todayStr = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
      var res = {
        date: todayStr,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0, count: 0
      };

      for (var i = 0; i < rows.length; i++) {
        var rDate = formatCellDate(rows[i][1]);
        if (rDate === todayStr) {
          var tType = String(rows[i][3]).toUpperCase();
          var tAmt = Number(rows[i][4]) || 0;
          var tMeth = String(rows[i][5]).toLowerCase();
          res.count++;

          if (tType === "THU") {
            res.total_thu += tAmt;
            if (tMeth.indexOf("khoản") >= 0 || tMeth.indexOf("transfer") >= 0) {
              res.thu_transfer += tAmt;
            } else {
              res.thu_cash += tAmt;
            }
          } else {
            res.total_chi += tAmt;
            if (tMeth.indexOf("khoản") >= 0 || tMeth.indexOf("transfer") >= 0) {
              res.chi_transfer += tAmt;
            } else {
              res.chi_cash += tAmt;
            }
          }
        }
      }
      res.balance = res.total_thu - res.total_chi;
      return jsonResponse(res);
    }

    // ==========================================
    // 4. TRUY VẤN TỔNG KẾT THÁNG (MONTH)
    // ==========================================
    if (action === "month") {
      var now = new Date();
      var monthPrefix = Utilities.formatDate(now, "Asia/Ho_Chi_Minh", "yyyy-MM");
      var monthRes = {
        month: monthPrefix,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0,
        categories_chi: {},
        categories_thu: {}
      };

      for (var m = 0; m < rows.length; m++) {
        var rowDate = formatCellDate(rows[m][1]).substring(0, 7);
        if (rowDate === monthPrefix) {
          var type = String(rows[m][3]).toUpperCase();
          var amt = Number(rows[m][4]) || 0;
          var meth = String(rows[m][5]).toLowerCase();
          var cat = String(rows[m][6]) || "Khác";

          if (type === "THU") {
            monthRes.total_thu += amt;
            if (meth.indexOf("khoản") >= 0) monthRes.thu_transfer += amt;
            else monthRes.thu_cash += amt;
            monthRes.categories_thu[cat] = (monthRes.categories_thu[cat] || 0) + amt;
          } else {
            monthRes.total_chi += amt;
            if (meth.indexOf("khoản") >= 0) monthRes.chi_transfer += amt;
            else monthRes.chi_cash += amt;
            monthRes.categories_chi[cat] = (monthRes.categories_chi[cat] || 0) + amt;
          }
        }
      }
      monthRes.balance = monthRes.total_thu - monthRes.total_chi;
      return jsonResponse(monthRes);
    }

    // ==========================================
    // 5. TRUY VẤN 10 GIAO DỊCH GẦN NHẤT (RECENT)
    // ==========================================
    if (action === "recent") {
      var recentItems = [];
      var startIdx = Math.max(0, rows.length - 10);
      for (var k = rows.length - 1; k >= startIdx; k--) {
        recentItems.push({
          id: rows[k][0],
          date: formatCellDate(rows[k][1]),
          time: formatCellTime(rows[k][2]),
          type: rows[k][3],
          amount: rows[k][4],
          payment_method: rows[k][5],
          category: rows[k][6],
          description: rows[k][7]
        });
      }
      return jsonResponse({ status: "success", items: recentItems });
    }

    return jsonResponse({ status: "unknown_action" });

  } catch (err) {
    return jsonResponse({ status: "error", message: err.toString() });
  }
}

function initHeaderIfNeeded(sheet) {
  if (sheet.getLastRow() === 0) {
    var headers = [
      "ID", "Ngày", "Giờ", "Loại", "Số Tiền", 
      "Hình Thức", "Danh Mục", "Nội Dung", "Nguồn Ghi"
    ];
    sheet.appendRow(headers);
    var headerRange = sheet.getRange(1, 1, 1, headers.length);
    headerRange.setBackground("#1F497D");
    headerRange.setFontColor("#FFFFFF");
    headerRange.setFontWeight("bold");
    headerRange.setHorizontalAlignment("center");
    sheet.setFrozenRows(1);
  }
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function formatCellDate(val) {
  if (!val) return "";
  if (val instanceof Date) {
    return Utilities.formatDate(val, "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
  }
  var s = String(val).trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    return s.substring(0, 10);
  }
  try {
    var d = new Date(s);
    if (!isNaN(d.getTime())) {
      return Utilities.formatDate(d, "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
    }
  } catch (e) {}
  return s.substring(0, 10);
}

function formatCellTime(val) {
  if (!val) return "";
  if (val instanceof Date) {
    return Utilities.formatDate(val, "Asia/Ho_Chi_Minh", "HH:mm:ss");
  }
  var s = String(val).trim();
  if (/^\d{2}:\d{2}/.test(s)) {
    return s.substring(0, 8);
  }
  return s;
}
