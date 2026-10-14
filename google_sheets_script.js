/**
 * =========================================================================
 * GOOGLE APPS SCRIPT: HỆ QUẢN TRỊ CƠ SỞ DỮ LIỆU SỔ QUỸ TRÊN GOOGLE SHEETS
 * PHIÊN BẢN ĐA NIÊN ĐỘ (MULTI-YEAR SHEETS) & TRUY VẤN NÂNG CAO
 * =========================================================================
 * 
 * TÍNH NĂNG:
 * 1. Mỗi năm một Sheet riêng (VD: "2026", "2025", "2027"...), tự động tạo khi có dữ liệu.
 * 2. Tự động định dạng tiêu đề, cố định dòng 1 (Freeze row 1), định dạng tiền tệ và căn lề.
 * 3. Hỗ trợ truy vấn ngày cụ thể, khoảng thời gian, tháng chỉ định, và cả năm.
 * 4. Hỗ trợ xóa giao dịch trên toàn bộ các Sheet năm.
 * 
 * HƯỚNG DẪN CẬP NHẬT:
 * 1. Mở file Google Sheets -> Chọn menu "Tiện ích mở rộng" (Extensions) -> "Apps Script"
 * 2. Xóa hết mã cũ, dán toàn bộ nội dung file này và bấm "Lưu" (Ctrl + S)
 * 3. Bấm "Triển khai" (Deploy) -> "Quản lý bản triển khai" (Manage deployments)
 *    -> Bấm biểu tượng ✏️ (Chỉnh sửa) -> Chọn Phiên bản: "Phiên bản mới" (New version) -> Bấm "Triển khai" (Deploy).
 */

// =========================================================================
// 1. doPost: TIẾP NHẬN THÊM VÀ XÓA DỮ LIỆU TỪ BOT
// =========================================================================
function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var payload = JSON.parse(rawData);
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // ----------------------------------------------------
    // A. XỬ LÝ LỆNH XÓA (DELETE)
    // ----------------------------------------------------
    if (payload.action === "delete") {
      var targetId = Number(payload.id);
      var yearSheets = getAllYearSheets(ss);

      for (var s = 0; s < yearSheets.length; s++) {
        var sheet = yearSheets[s];
        var lastRow = sheet.getLastRow();
        if (lastRow > 1) {
          var idRange = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
          for (var i = idRange.length - 1; i >= 0; i--) {
            if (Number(idRange[i][0]) === targetId) {
              sheet.deleteRow(i + 2);
              return jsonResponse({
                status: "success",
                deleted_id: targetId,
                sheet: sheet.getName()
              });
            }
          }
        }
      }
      return jsonResponse({ status: "not_found", message: "Không tìm thấy ID trên các sheet" });
    }

    // ----------------------------------------------------
    // B. XỬ LÝ LỆNH THÊM GIAO DỊCH (ADD)
    // ----------------------------------------------------
    var items = [];
    if (payload.action === "add" && payload.data) {
      items = Array.isArray(payload.data) ? payload.data : [payload.data];
    } else if (Array.isArray(payload)) {
      items = payload;
    } else {
      items = [payload];
    }

    if (items.length === 0) {
      return jsonResponse({ status: "empty", count: 0 });
    }

    // Phân nhóm giao dịch theo năm dựa vào trường date (YYYY-MM-DD)
    var itemsByYear = {};
    for (var j = 0; j < items.length; j++) {
      var it = items[j];
      var yearStr = getYearFromDateStr(it.date);
      if (!itemsByYear[yearStr]) {
        itemsByYear[yearStr] = [];
      }
      itemsByYear[yearStr].push(it);
    }

    var totalAdded = 0;
    var firstId = null;

    // Ghi vào từng sheet năm tương ứng
    for (var yKey in itemsByYear) {
      var sheetYear = getOrCreateYearSheet(ss, yKey);
      var yearItems = itemsByYear[yKey];
      var startRow = sheetYear.getLastRow() + 1;
      var rowsToAdd = [];

      for (var k = 0; k < yearItems.length; k++) {
        var item = yearItems[k];
        var isThu = (item.type || "").toLowerCase() === "thu";
        var typeText = isThu ? "THU" : "CHI";
        var methLower = (item.payment_method || "").toLowerCase();
        var methodText = (methLower.indexOf("khoản") >= 0 || methLower.indexOf("transfer") >= 0 || methLower.indexOf("ck") >= 0)
          ? "Chuyển khoản" : "Tiền mặt";
        var amount = Number(item.amount) || 0;
        var rowId = item.id || (startRow + k - 1);

        if (!firstId) firstId = rowId;

        rowsToAdd.push([
          rowId,
          item.date || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd"),
          item.time || Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "HH:mm:ss"),
          typeText,
          amount,
          methodText,
          item.category || "",
          item.description || "",
          item.source || "telegram"
        ]);
      }

      if (rowsToAdd.length > 0) {
        var numRows = rowsToAdd.length;
        var range = sheetYear.getRange(startRow, 1, numRows, 9);
        range.setValues(rowsToAdd);

        // Định dạng màu sắc và tiền tệ cho các hàng mới
        for (var r = 0; r < numRows; r++) {
          var currRowIdx = startRow + r;
          var isThuRow = rowsToAdd[r][3] === "THU";

          var typeCell = sheetYear.getRange(currRowIdx, 4);
          typeCell.setFontWeight("bold");
          typeCell.setHorizontalAlignment("center");
          typeCell.setFontColor(isThuRow ? "#274E13" : "#A61C1C");

          var amountCell = sheetYear.getRange(currRowIdx, 5);
          amountCell.setNumberFormat('#,##0" ₫"');
          amountCell.setFontWeight("bold");
          amountCell.setHorizontalAlignment("right");

          sheetYear.getRange(currRowIdx, 1).setHorizontalAlignment("center");
          sheetYear.getRange(currRowIdx, 2).setHorizontalAlignment("center");
          sheetYear.getRange(currRowIdx, 3).setHorizontalAlignment("center");
          sheetYear.getRange(currRowIdx, 6).setHorizontalAlignment("center");
        }
        totalAdded += numRows;
      }
    }

    return jsonResponse({ status: "success", count: totalAdded, id: firstId });

  } catch (err) {
    return jsonResponse({ status: "error", message: err.toString() });
  }
}

// =========================================================================
// 2. doGet: TRUY VẤN DỮ LIỆU ĐA CHIỀU (NGÀY, KHOẢNG, THÁNG, NĂM, GẦN NHẤT)
// =========================================================================
function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var action = (e && e.parameter && e.parameter.action) ? e.parameter.action : "ping";

    if (action === "ping") {
      var sheets = getAllYearSheets(ss);
      var sheetNames = sheets.map(function(s) { return s.getName(); });
      return jsonResponse({ status: "ok", message: "Google Sheets Multi-Year DB Online", sheets: sheetNames });
    }

    // ----------------------------------------------------
    // A. TRUY VẤN NGÀY CỤ THỂ HOẶC HÔM NAY (DAY / TODAY)
    // ----------------------------------------------------
    if (action === "day" || action === "today") {
      var dateParam = (e.parameter && e.parameter.date) ? e.parameter.date.trim() : "";
      if (!dateParam) {
        dateParam = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
      }
      var targetYear = getYearFromDateStr(dateParam);
      var sheet = getOrCreateYearSheet(ss, targetYear);
      var rows = getAllRowsFromSheet(sheet);

      var resDay = {
        date: dateParam,
        year: targetYear,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0, count: 0,
        items: []
      };

      for (var i = 0; i < rows.length; i++) {
        var rDate = formatCellDate(rows[i][1]);
        if (rDate === dateParam) {
          var tType = String(rows[i][3]).toUpperCase();
          var tAmt = Number(rows[i][4]) || 0;
          var tMeth = String(rows[i][5]).toLowerCase();
          resDay.count++;

          var isTransfer = tMeth.indexOf("khoản") >= 0 || tMeth.indexOf("transfer") >= 0 || tMeth.indexOf("ck") >= 0;
          if (tType === "THU") {
            resDay.total_thu += tAmt;
            if (isTransfer) resDay.thu_transfer += tAmt;
            else resDay.thu_cash += tAmt;
          } else {
            resDay.total_chi += tAmt;
            if (isTransfer) resDay.chi_transfer += tAmt;
            else resDay.chi_cash += tAmt;
          }

          resDay.items.push({
            id: rows[i][0],
            date: rDate,
            time: formatCellTime(rows[i][2]),
            type: rows[i][3],
            amount: tAmt,
            payment_method: rows[i][5],
            category: rows[i][6],
            description: rows[i][7]
          });
        }
      }
      resDay.balance = resDay.total_thu - resDay.total_chi;
      return jsonResponse(resDay);
    }

    // ----------------------------------------------------
    // B. TRUY VẤN THÁNG CHỈ ĐỊNH (MONTH)
    // ----------------------------------------------------
    if (action === "month") {
      var monthParam = (e.parameter && e.parameter.month) ? e.parameter.month.trim() : "";
      if (!monthParam) {
        monthParam = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM");
      }
      var targetMonthYear = getYearFromDateStr(monthParam);
      var monthSheet = getOrCreateYearSheet(ss, targetMonthYear);
      var mRows = getAllRowsFromSheet(monthSheet);

      var monthRes = {
        month: monthParam,
        year: targetMonthYear,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0, count: 0,
        categories_chi: {},
        categories_thu: {}
      };

      for (var m = 0; m < mRows.length; m++) {
        var rowD = formatCellDate(mRows[m][1]);
        if (rowD.substring(0, 7) === monthParam) {
          var type = String(mRows[m][3]).toUpperCase();
          var amt = Number(mRows[m][4]) || 0;
          var meth = String(mRows[m][5]).toLowerCase();
          var cat = String(mRows[m][6]) || "Khác";
          var isCk = meth.indexOf("khoản") >= 0 || meth.indexOf("transfer") >= 0 || meth.indexOf("ck") >= 0;

          monthRes.count++;
          if (type === "THU") {
            monthRes.total_thu += amt;
            if (isCk) monthRes.thu_transfer += amt;
            else monthRes.thu_cash += amt;
            monthRes.categories_thu[cat] = (monthRes.categories_thu[cat] || 0) + amt;
          } else {
            monthRes.total_chi += amt;
            if (isCk) monthRes.chi_transfer += amt;
            else monthRes.chi_cash += amt;
            monthRes.categories_chi[cat] = (monthRes.categories_chi[cat] || 0) + amt;
          }
        }
      }
      monthRes.balance = monthRes.total_thu - monthRes.total_chi;
      return jsonResponse(monthRes);
    }

    // ----------------------------------------------------
    // C. TRUY VẤN THEO KHOẢNG THỜI GIAN (RANGE)
    // ----------------------------------------------------
    if (action === "range") {
      var startDate = (e.parameter && e.parameter.start_date) ? e.parameter.start_date.trim() : "";
      var endDate = (e.parameter && e.parameter.end_date) ? e.parameter.end_date.trim() : "";
      if (!startDate) startDate = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-01");
      if (!endDate) endDate = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");

      var startYear = Number(getYearFromDateStr(startDate));
      var endYear = Number(getYearFromDateStr(endDate));
      var rangeRows = [];

      for (var y = startYear; y <= endYear; y++) {
        var sh = ss.getSheetByName(String(y));
        if (sh) {
          var shRows = getAllRowsFromSheet(sh);
          rangeRows = rangeRows.concat(shRows);
        }
      }

      var rangeRes = {
        start_date: startDate,
        end_date: endDate,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0, count: 0,
        categories_chi: {},
        categories_thu: {},
        items: []
      };

      for (var r = 0; r < rangeRows.length; r++) {
        var dt = formatCellDate(rangeRows[r][1]);
        if (dt >= startDate && dt <= endDate) {
          var rType = String(rangeRows[r][3]).toUpperCase();
          var rAmt = Number(rangeRows[r][4]) || 0;
          var rMeth = String(rangeRows[r][5]).toLowerCase();
          var rCat = String(rangeRows[r][6]) || "Khác";
          var isTrans = rMeth.indexOf("khoản") >= 0 || rMeth.indexOf("transfer") >= 0 || rMeth.indexOf("ck") >= 0;

          rangeRes.count++;
          if (rType === "THU") {
            rangeRes.total_thu += rAmt;
            if (isTrans) rangeRes.thu_transfer += rAmt;
            else rangeRes.thu_cash += rAmt;
            rangeRes.categories_thu[rCat] = (rangeRes.categories_thu[rCat] || 0) + rAmt;
          } else {
            rangeRes.total_chi += rAmt;
            if (isTrans) rangeRes.chi_transfer += rAmt;
            else rangeRes.chi_cash += rAmt;
            rangeRes.categories_chi[rCat] = (rangeRes.categories_chi[rCat] || 0) + rAmt;
          }

          rangeRes.items.push({
            id: rangeRows[r][0],
            date: dt,
            time: formatCellTime(rangeRows[r][2]),
            type: rangeRows[r][3],
            amount: rAmt,
            payment_method: rangeRows[r][5],
            category: rCat,
            description: rangeRows[r][7],
            source: rangeRows[r][8]
          });
        }
      }
      rangeRes.balance = rangeRes.total_thu - rangeRes.total_chi;
      return jsonResponse(rangeRes);
    }

    // ----------------------------------------------------
    // D. TRUY VẤN BÁO CÁO CẢ NĂM (YEAR)
    // ----------------------------------------------------
    if (action === "year") {
      var yearParam = (e.parameter && e.parameter.year) ? e.parameter.year.trim() : "";
      if (!yearParam) {
        yearParam = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy");
      }
      var ySheet = getOrCreateYearSheet(ss, yearParam);
      var yRows = getAllRowsFromSheet(ySheet);

      var yearRes = {
        year: yearParam,
        total_thu: 0, total_chi: 0,
        thu_cash: 0, thu_transfer: 0,
        chi_cash: 0, chi_transfer: 0,
        balance: 0, count: 0,
        monthly_stats: [],
        categories_chi: {},
        categories_thu: {}
      };

      // Khởi tạo thống kê 12 tháng
      for (var mo = 1; mo <= 12; mo++) {
        yearRes.monthly_stats.push({
          month: mo,
          total_thu: 0,
          total_chi: 0,
          balance: 0,
          count: 0
        });
      }

      for (var yIdx = 0; yIdx < yRows.length; yIdx++) {
        var cDate = formatCellDate(yRows[yIdx][1]);
        if (cDate.substring(0, 4) === yearParam) {
          var yType = String(yRows[yIdx][3]).toUpperCase();
          var yAmt = Number(yRows[yIdx][4]) || 0;
          var yMeth = String(yRows[yIdx][5]).toLowerCase();
          var yCat = String(yRows[yIdx][6]) || "Khác";
          var isCkY = yMeth.indexOf("khoản") >= 0 || yMeth.indexOf("transfer") >= 0 || yMeth.indexOf("ck") >= 0;

          var mIndex = Number(cDate.substring(5, 7)) - 1;

          yearRes.count++;
          if (yType === "THU") {
            yearRes.total_thu += yAmt;
            if (isCkY) yearRes.thu_transfer += yAmt;
            else yearRes.thu_cash += yAmt;
            yearRes.categories_thu[yCat] = (yearRes.categories_thu[yCat] || 0) + yAmt;

            if (mIndex >= 0 && mIndex < 12) {
              yearRes.monthly_stats[mIndex].total_thu += yAmt;
              yearRes.monthly_stats[mIndex].count++;
            }
          } else {
            yearRes.total_chi += yAmt;
            if (isCkY) yearRes.chi_transfer += yAmt;
            else yearRes.chi_cash += yAmt;
            yearRes.categories_chi[yCat] = (yearRes.categories_chi[yCat] || 0) + yAmt;

            if (mIndex >= 0 && mIndex < 12) {
              yearRes.monthly_stats[mIndex].total_chi += yAmt;
              yearRes.monthly_stats[mIndex].count++;
            }
          }
        }
      }

      for (var mi = 0; mi < 12; mi++) {
        yearRes.monthly_stats[mi].balance = yearRes.monthly_stats[mi].total_thu - yearRes.monthly_stats[mi].total_chi;
      }
      yearRes.balance = yearRes.total_thu - yearRes.total_chi;
      return jsonResponse(yearRes);
    }

    // ----------------------------------------------------
    // E. TRUY VẤN GIAO DỊCH GẦN NHẤT (RECENT)
    // ----------------------------------------------------
    if (action === "recent") {
      var limit = Number(e.parameter && e.parameter.limit) || 10;
      var allYearSheets = getAllYearSheets(ss);
      var collectedItems = [];

      for (var sIdx = 0; sIdx < allYearSheets.length; sIdx++) {
        var shObj = allYearSheets[sIdx];
        var shData = getAllRowsFromSheet(shObj);
        for (var rowIdx = shData.length - 1; rowIdx >= 0; rowIdx--) {
          collectedItems.push({
            id: shData[rowIdx][0],
            date: formatCellDate(shData[rowIdx][1]),
            time: formatCellTime(shData[rowIdx][2]),
            type: shData[rowIdx][3],
            amount: shData[rowIdx][4],
            payment_method: shData[rowIdx][5],
            category: shData[rowIdx][6],
            description: shData[rowIdx][7],
            source: shData[rowIdx][8]
          });
          if (collectedItems.length >= limit) break;
        }
        if (collectedItems.length >= limit) break;
      }

      return jsonResponse({ status: "success", items: collectedItems });
    }

    return jsonResponse({ status: "unknown_action" });

  } catch (err) {
    return jsonResponse({ status: "error", message: err.toString() });
  }
}

// =========================================================================
// 3. CÁC HÀM TIỆN ÍCH QUẢN TRỊ SHEET VÀ ĐỊNH DẠNG
// =========================================================================

/**
 * Lấy hoặc tạo Sheet theo năm (VD: "2026").
 * Tự động chuyển đổi "Trang tính 1" / "Sheet1" sang "2026" nếu bảng tính mới tạo.
 */
function getOrCreateYearSheet(ss, yearStr) {
  var target = ss.getSheetByName(yearStr);
  if (target) {
    initHeaderIfNeeded(target);
    return target;
  }

  // Kiểm tra sheet mặc định chưa đổi tên
  var defaultSheet = ss.getSheetByName("Trang tính 1") || ss.getSheetByName("Sheet1");
  if (defaultSheet && ss.getSheets().length === 1) {
    defaultSheet.setName(yearStr);
    initHeaderIfNeeded(defaultSheet);
    return defaultSheet;
  }

  // Tạo mới sheet theo năm
  target = ss.insertSheet(yearStr);
  initHeaderIfNeeded(target);
  return target;
}

/**
 * Lấy toàn bộ các sheet theo năm trong bảng tính (sắp xếp giảm dần theo năm).
 */
function getAllYearSheets(ss) {
  var sheets = ss.getSheets();
  var yearSheets = [];
  for (var i = 0; i < sheets.length; i++) {
    var name = sheets[i].getName().trim();
    if (/^\d{4}$/.test(name)) {
      yearSheets.push(sheets[i]);
    }
  }

  yearSheets.sort(function(a, b) {
    return Number(b.getName()) - Number(a.getName());
  });

  if (yearSheets.length === 0) {
    var active = ss.getActiveSheet();
    if (active) yearSheets.push(active);
  }
  return yearSheets;
}

/**
 * Lấy tất cả các dòng dữ liệu trong 1 sheet (bỏ qua dòng tiêu đề 1).
 */
function getAllRowsFromSheet(sheet) {
  var lastRow = sheet.getLastRow();
  if (lastRow <= 1) return [];
  return sheet.getRange(2, 1, lastRow - 1, 9).getValues();
}

/**
 * Trích xuất năm từ chuỗi ngày (YYYY-MM-DD hoặc YYYY-MM).
 */
function getYearFromDateStr(dateStr) {
  if (!dateStr) return Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy");
  var match = String(dateStr).match(/^(\d{4})/);
  if (match) return match[1];
  return Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy");
}

/**
 * Khởi tạo tiêu đề chuẩn 9 cột nếu sheet còn trống.
 */
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
