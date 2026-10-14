"""
Pure-Python WinZip AES-256 Decryptor & Extractor.
Hoàn toàn độc lập, không phụ thuộc vào bất kỳ thư viện C hay pip package ngoài nào.
Hỗ trợ giải nén file ZIP ngân hàng mã hóa AES-256 (Techcombank, Vietcombank, MBBank...)
trên mọi môi trường (Vercel Serverless, AWS Lambda, Docker, Linux, Windows, macOS).
"""

import os
import zlib
import hmac
import struct
import hashlib
import zipfile
from pathlib import Path
from typing import List, Tuple, Optional, Union

# Bảng S-box chuẩn AES (Rijndael)
_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16
]
_RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]

def _sub_word(w: int) -> int:
    return (_SBOX[(w >> 24) & 0xff] << 24) | (_SBOX[(w >> 16) & 0xff] << 16) | (_SBOX[(w >> 8) & 0xff] << 8) | _SBOX[w & 0xff]

def _rot_word(w: int) -> int:
    return ((w << 8) & 0xffffffff) | (w >> 24)

def _key_expansion_256(key_bytes: bytes) -> List[int]:
    w = [int.from_bytes(key_bytes[i*4:(i+1)*4], 'big') for i in range(8)]
    for i in range(8, 60):
        temp = w[i - 1]
        if i % 8 == 0:
            temp = _sub_word(_rot_word(temp)) ^ (_RCON[i // 8] << 24)
        elif i % 8 == 4:
            temp = _sub_word(temp)
        w.append(w[i - 8] ^ temp)
    return w

def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1b) & 0xff if (a & 0x80) else (a << 1)

def _aes_encrypt_block(block16: bytes, round_keys: List[int]) -> bytes:
    state = [[block16[r + 4*c] for c in range(4)] for r in range(4)]
    # AddRoundKey ban đầu
    for c in range(4):
        kw = round_keys[c]
        for r in range(4):
            state[r][c] ^= (kw >> (24 - 8*r)) & 0xff

    # 13 rounds chuẩn
    for rnd in range(1, 14):
        for r in range(4):
            for c in range(4):
                state[r][c] = _SBOX[state[r][c]]
        state[1] = state[1][1:] + state[1][:1]
        state[2] = state[2][2:] + state[2][:2]
        state[3] = state[3][3:] + state[3][:3]
        for c in range(4):
            s0, s1, s2, s3 = state[0][c], state[1][c], state[2][c], state[3][c]
            state[0][c] = _xtime(s0 ^ s1) ^ s1 ^ s2 ^ s3
            state[1][c] = _xtime(s1 ^ s2) ^ s2 ^ s3 ^ s0
            state[2][c] = _xtime(s2 ^ s3) ^ s3 ^ s0 ^ s1
            state[3][c] = _xtime(s3 ^ s0) ^ s0 ^ s1 ^ s2
        for c in range(4):
            kw = round_keys[rnd * 4 + c]
            for r in range(4):
                state[r][c] ^= (kw >> (24 - 8*r)) & 0xff

    # Vòng cuối không có MixColumns
    for r in range(4):
        for c in range(4):
            state[r][c] = _SBOX[state[r][c]]
    state[1] = state[1][1:] + state[1][:1]
    state[2] = state[2][2:] + state[2][:2]
    state[3] = state[3][3:] + state[3][:3]
    for c in range(4):
        kw = round_keys[14 * 4 + c]
        for r in range(4):
            state[r][c] ^= (kw >> (24 - 8*r)) & 0xff

    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[r + 4*c] = state[r][c]
    return bytes(out)

# Kiểm tra nếu môi trường có thư viện cryptography / PyCryptodome C-extension để tối ưu tốc độ
_FAST_AES_BACKEND = None
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    _FAST_AES_BACKEND = "cryptography"
except Exception:
    try:
        from Cryptodome.Cipher import AES as _PyCryptoAES
        from Cryptodome.Util import Counter as _PyCryptoCounter
        _FAST_AES_BACKEND = "Cryptodome"
    except Exception:
        try:
            from Crypto.Cipher import AES as _PyCryptoAES
            from Crypto.Util import Counter as _PyCryptoCounter
            _FAST_AES_BACKEND = "Crypto"
        except Exception:
            _FAST_AES_BACKEND = "pure_python"


def aes_ctr_decrypt(ciphertext: bytes, enckey: bytes) -> bytes:
    """Giải mã dữ liệu AES-256 CTR (128-bit little endian counter bắt đầu từ 1)."""
    # 1. Thử dùng cryptography (nếu có)
    if _FAST_AES_BACKEND == "cryptography":
        try:
            nonce_16 = (1).to_bytes(16, byteorder='little')
            cipher = Cipher(algorithms.AES(enckey), modes.CTR(nonce_16), backend=default_backend())
            decryptor = cipher.decryptor()
            return decryptor.update(ciphertext) + decryptor.finalize()
        except Exception:
            pass

    # 2. Thử dùng PyCryptodome (nếu có)
    if _FAST_AES_BACKEND in ["Cryptodome", "Crypto"]:
        try:
            ctr = _PyCryptoCounter.new(nbits=128, little_endian=True, initial_value=1)
            cipher = _PyCryptoAES.new(enckey, _PyCryptoAES.MODE_CTR, counter=ctr)
            return cipher.decrypt(ciphertext)
        except Exception:
            pass

    # 3. Pure Python fallback (luôn hoạt động 100% không cần phụ thuộc gì)
    round_keys = _key_expansion_256(enckey)
    out = bytearray(len(ciphertext))
    counter = 1
    for offset in range(0, len(ciphertext), 16):
        counter_block = counter.to_bytes(16, byteorder='little')
        keystream = _aes_encrypt_block(counter_block, round_keys)
        chunk = ciphertext[offset:offset+16]
        for i in range(len(chunk)):
            out[offset + i] = chunk[i] ^ keystream[i]
        counter += 1
    return bytes(out)


def is_winzip_aes(zip_path: Union[str, Path]) -> bool:
    """Kiểm tra file zip có chứa tệp mã hóa WinZip AES (Method 99) không."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for zinfo in zf.infolist():
                if zinfo.compress_type == 99:
                    return True
        return False
    except Exception:
        return False


def extract_winzip_aes(zip_path: Union[str, Path], extract_dir: Union[str, Path], password: str) -> Tuple[List[Path], Optional[str]]:
    """
    Giải nén toàn bộ tệp trong ZIP hỗ trợ cả WinZip AES-256 và ZipCrypto / Uncompressed.
    Returns:
        (extracted_files_list, error_code)
        error_code: None nếu thành công, hoặc 'BAD_PASSWORD', 'CORRUPTED_ZIP'
    """
    zip_path = Path(zip_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    pwd_bytes = password.encode('utf-8') if password else b""

    extracted_files: List[Path] = []

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for zinfo in zf.infolist():
                target_path = extract_dir / zinfo.filename
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Trường hợp 1: Tệp mã hóa WinZip AES-256 (Method 99)
                if zinfo.compress_type == 99:
                    with open(zip_path, 'rb') as f:
                        f.seek(zinfo.header_offset)
                        hdr = f.read(30)
                        if len(hdr) < 30 or hdr[:4] != b'PK\x03\x04':
                            return [], "CORRUPTED_ZIP"
                        fn_len = int.from_bytes(hdr[26:28], 'little')
                        ex_len = int.from_bytes(hdr[28:30], 'little')
                        extra = f.read(ex_len)

                        # Xác định actual_compress_type từ extra field 0x9901
                        actual_comp = 8  # Deflate mặc định
                        strength = 3     # 3 = 256-bit
                        idx = 0
                        while idx < len(extra):
                            if idx + 4 > len(extra):
                                break
                            tag, sz = struct.unpack('<HH', extra[idx:idx+4])
                            if tag == 0x9901 and sz >= 7:
                                strength = extra[idx+8]
                                actual_comp = struct.unpack('<H', extra[idx+9:idx+11])[0]
                                break
                            idx += 4 + sz

                        salt_len = 16 if strength == 3 else (12 if strength == 2 else 8)
                        key_len = 32 if strength == 3 else (24 if strength == 2 else 16)

                        f.seek(zinfo.header_offset + 30 + fn_len + ex_len)
                        salt = f.read(salt_len)
                        pwd_ver = f.read(2)
                        cdata_len = zinfo.compress_size - salt_len - 2 - 10
                        cdata = f.read(cdata_len)
                        auth_code = f.read(10)

                        if not pwd_bytes:
                            return [], "BAD_PASSWORD"

                        # Sinh khóa qua PBKDF2 chuẩn hashlib
                        keymaterial = hashlib.pbkdf2_hmac('sha1', pwd_bytes, salt, 1000, 2*key_len + 2)
                        enckey = keymaterial[:key_len]
                        mackey = keymaterial[key_len:2*key_len]
                        calc_pv = keymaterial[2*key_len:2*key_len + 2]

                        if calc_pv != pwd_ver:
                            return [], "BAD_PASSWORD"

                        calc_mac = hmac.new(mackey, cdata, hashlib.sha1).digest()[:10]
                        if calc_mac != auth_code:
                            return [], "BAD_PASSWORD"

                        # Giải mã AES CTR
                        decrypted = aes_ctr_decrypt(cdata, enckey)

                        # Giải nén
                        if actual_comp == 8:
                            decompressed = zlib.decompress(decrypted, -zlib.MAX_WBITS)
                        elif actual_comp == 0:
                            decompressed = decrypted
                        else:
                            return [], "CORRUPTED_ZIP"

                        with open(target_path, 'wb') as out_f:
                            out_f.write(decompressed)
                        extracted_files.append(target_path)

                # Trường hợp 2: Tệp không nén AES (dùng standard zipfile)
                else:
                    zf.extract(zinfo, extract_dir, pwd=pwd_bytes if pwd_bytes else None)
                    if target_path.exists():
                        extracted_files.append(target_path)

        return extracted_files, None

    except zipfile.BadZipFile:
        return [], "CORRUPTED_ZIP"
    except RuntimeError as e:
        err_str = str(e).lower()
        if "password" in err_str or "encrypted" in err_str:
            return [], "BAD_PASSWORD"
        return [], "CORRUPTED_ZIP"
    except Exception:
        return [], "CORRUPTED_ZIP"
