import math
import socket
import struct
import threading
import time
from datetime import datetime, timedelta

# ---------------- 默认配置（可用命令行参数覆盖，见 --help） ----------------
SERVER_HOST = '127.0.0.1'  # 云平台 IP
SERVER_PORT = 8888         # 云平台端口
PILE_SN = b'\x77\x03\x10\x00\x00\x18\x05'  # 桩编码 BCD 7字节（示例桩号 77031000000001）

GUN_COUNT = 2
GUN_NO = 2  # 当前模拟枪号（1..GUN_COUNT）
PROTOCOL_VER = 0x0F  # 协议版本 V1.5（0x0F）
PROGRAM_VER = b'V4.1.50\x00'  # 8字节 ASCII
NET_TYPE = 0x01  # LAN
SIM_CARD = b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'  # 10字节
OPERATOR = 0x04  # 其他

HEARTBEAT_INTERVAL = 10  # 秒

AMOUNT_INCREMENT = 0.02  # 每次递增0.10元
MAX_AMOUNT = 2.00  # 最高不超过2.00元

# 命令码（奇数上行，偶数下行）
CMD_LOGIN = 0x01
CMD_LOGIN_RESP = 0x02
CMD_HEARTBEAT = 0x03
CMD_HEARTBEAT_RESP = 0x04
CMD_BILL_CHECK = 0x05
CMD_BILL_CHECK_RESP = 0x06
CMD_BILL_REQUEST = 0x09
CMD_BILL_REQUEST_RESP = 0x0A
# 实时数据相关
CMD_READ_REALTIME = 0x12
CMD_UPLOAD_REALTIME = 0x13
CMD_CHARGE_HANDSHAKE = 0x15
CMD_PARAM_CONFIG = 0x17
CMD_CHARGE_END = 0x19
CMD_ERROR_REPORT = 0x1B
CMD_BMS_STOP = 0x1D
CMD_CHARGER_STOP = 0x21
CMD_BMS_DEMAND = 0x23
CMD_BMS_INFO = 0x25

# 运营交互
CMD_CHARGE_REQUEST = 0x31
CMD_CHARGE_CONFIRM = 0x32
CMD_REMOTE_START_RESP = 0x33
CMD_REMOTE_START_CMD = 0x34
CMD_REMOTE_STOP_RESP = 0x35
CMD_REMOTE_STOP_CMD = 0x36
CMD_TRADE_RECORD = 0x3B
CMD_TRADE_CONFIRM = 0x40
CMD_BALANCE_UPDATE_RESP = 0x41
CMD_BALANCE_UPDATE_CMD = 0x42

# 平台设置
CMD_PARAM_SET_RESP = 0x51
CMD_PARAM_SET_CMD = 0x52
CMD_TIME_SET_RESP = 0x55
CMD_TIME_SET_CMD = 0x56
CMD_BILL_SET_RESP = 0x57
CMD_BILL_SET_CMD = 0x58

# 远程维护
CMD_REMOTE_RESTART_RESP = 0x91
CMD_REMOTE_RESTART_CMD = 0x92
CMD_REMOTE_UPDATE_RESP = 0x93
CMD_REMOTE_UPDATE_CMD = 0x94

# 地锁
CMD_LOCK_STATUS = 0x61
CMD_LOCK_CTRL_CMD = 0x62
CMD_LOCK_CTRL_RESP = 0x63

# 状态定义
STATUS_OFFLINE = 0x00
STATUS_FAULT = 0x01
STATUS_IDLE = 0x02
STATUS_CHARGING = 0x03

# 启动类型
START_TYPE_CARD = 0x01
START_TYPE_ACCOUNT = 0x02
START_TYPE_VIN = 0x03

# 交易类型
TRADE_TYPE_APP = 0x01
TRADE_TYPE_CARD = 0x02
TRADE_TYPE_OFFLINE_CARD = 0x04
TRADE_TYPE_VIN = 0x05


# CRC16 Modbus 表（协议附录已提供）
# crc_hi_table = [
#     0x00,0xc1,0x81,0x40,0x01,0xc0,0x80,0x41,0x01,0xc0,0x80,0x41,0x00,0xc1,0x81,0x40,
#     # ... 省略其余，完整表见协议附录或下面函数内定义
#     # 为节省空间，这里只贴计算函数，完整表可复制协议中的 gabyCRCHi / gabyCRCLo
# ]

def modbus_crc16(data: bytes) -> int:
    """Modbus CRC-16，协议指定算法，低字节在前输出数值形式"""
    crc_hi = 0xFF
    crc_lo = 0xFF

    # 完整 CRC 表（从 Java 代码复制，确保一致）
    crc_hi_table = [
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
        0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1,
        0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1,
        0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1,
        0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
        0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1,
        0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0,
        0x80, 0x41, 0x00, 0xC1, 0x81, 0x40
    ]

    crc_lo_table = [
        0x00, 0xC0, 0xC1, 0x01, 0xC3, 0x03, 0x02, 0xC2, 0xC6, 0x06,
        0x07, 0xC7, 0x05, 0xC5, 0xC4, 0x04, 0xCC, 0x0C, 0x0D, 0xCD,
        0x0F, 0xCF, 0xCE, 0x0E, 0x0A, 0xCA, 0xCB, 0x0B, 0xC9, 0x09,
        0x08, 0xC8, 0xD8, 0x18, 0x19, 0xD9, 0x1B, 0xDB, 0xDA, 0x1A,
        0x1E, 0xDE, 0xDF, 0x1F, 0xDD, 0x1D, 0x1C, 0xDC, 0x14, 0xD4,
        0xD5, 0x15, 0xD7, 0x17, 0x16, 0xD6, 0xD2, 0x12, 0x13, 0xD3,
        0x11, 0xD1, 0xD0, 0x10, 0xF0, 0x30, 0x31, 0xF1, 0x33, 0xF3,
        0xF2, 0x32, 0x36, 0xF6, 0xF7, 0x37, 0xF5, 0x35, 0x34, 0xF4,
        0x3C, 0xFC, 0xFD, 0x3D, 0xFF, 0x3F, 0x3E, 0xFE, 0xFA, 0x3A,
        0x3B, 0xFB, 0x39, 0xF9, 0xF8, 0x38, 0x28, 0xE8, 0xE9, 0x29,
        0xEB, 0x2B, 0x2A, 0xEA, 0xEE, 0x2E, 0x2F, 0xEF, 0x2D, 0xED,
        0xEC, 0x2C, 0xE4, 0x24, 0x25, 0xE5, 0x27, 0xE7, 0xE6, 0x26,
        0x22, 0xE2, 0xE3, 0x23, 0xE1, 0x21, 0x20, 0xE0, 0xA0, 0x60,
        0x61, 0xA1, 0x63, 0xA3, 0xA2, 0x62, 0x66, 0xA6, 0xA7, 0x67,
        0xA5, 0x65, 0x64, 0xA4, 0x6C, 0xAC, 0xAD, 0x6D, 0xAF, 0x6F,
        0x6E, 0xAE, 0xAA, 0x6A, 0x6B, 0xAB, 0x69, 0xA9, 0xA8, 0x68,
        0x78, 0xB8, 0xB9, 0x79, 0xBB, 0x7B, 0x7A, 0xBA, 0xBE, 0x7E,
        0x7F, 0xBF, 0x7D, 0xBD, 0xBC, 0x7C, 0xB4, 0x74, 0x75, 0xB5,
        0x77, 0xB7, 0xB6, 0x76, 0x72, 0xB2, 0xB3, 0x73, 0xB1, 0x71,
        0x70, 0xB0, 0x50, 0x90, 0x91, 0x51, 0x93, 0x53, 0x52, 0x92,
        0x96, 0x56, 0x57, 0x97, 0x55, 0x95, 0x94, 0x54, 0x9C, 0x5C,
        0x5D, 0x9D, 0x5F, 0x9F, 0x9E, 0x5E, 0x5A, 0x9A, 0x9B, 0x5B,
        0x99, 0x59, 0x58, 0x98, 0x88, 0x48, 0x49, 0x89, 0x4B, 0x8B,
        0x8A, 0x4A, 0x4E, 0x8E, 0x8F, 0x4F, 0x8D, 0x4D, 0x4C, 0x8C,
        0x44, 0x84, 0x85, 0x45, 0x87, 0x47, 0x46, 0x86, 0x82, 0x42,
        0x43, 0x83, 0x41, 0x81, 0x80, 0x40
    ]

    for byte in data:
        idx = crc_hi ^ byte
        crc_hi = crc_lo ^ crc_hi_table[idx]
        crc_lo = crc_lo_table[idx]

    return (crc_hi << 8) | crc_lo  # 返回大端数值形式 (high << 8 | low)


def build_frame(cmd: int, data_bytes: bytes = b'') -> bytes:
    # 序列号分配在发送锁外进行，但需要保证原子性
    with seq_lock:  # 使用序列号锁保护分配
        seq = seq_counter[0] % 65536
        seq_counter[0] += 1
    encrypt = 0x00
    length = 2 + 1 + 1 + len(data_bytes)  # seq(2) + encrypt(1) + cmd(1) + body
    header = struct.pack('<B H B B', length, seq, encrypt, cmd)  # BIN码低位在前
    payload = header + data_bytes  # 从 length 开始的 payload
    # ★关键：CRC从序列号域开始计算（跳过length字节），与Java服务端一致
    crc = modbus_crc16(payload[1:])
    frame = b'\x68' + payload + struct.pack('<H', crc)  # ★低字节在前

    # 调试输出：打印帧信息

    thread_name = threading.current_thread().name
    print(
        f"[{thread_name}] build_frame: cmd=0x{cmd:02X}, seq={seq}, len={len(frame)}, frame={frame.hex(' ')}, crc=0x{crc:04X}")

    return frame


seq_counter = [0]  # 全局序列号
seq_lock = threading.Lock()  # 序列号分配锁
send_lock = threading.Lock()  # socket发送锁，防止多线程并发发送导致数据交错
running_flag = True  # 全局运行标志，控制线程退出


def parse_frame(data: bytes):
    if len(data) < 7 or data[0] != 0x68:
        return None
    length = data[1]
    # 修改：允许接收数据长度 >= 期望长度（服务器可能少发字节）
    if len(data) < length + 4:
        print(f"长度不足! 期望={length + 3}, 实际={len(data)}")
        return None
    payload = data[2: -2]
    crc_recv = struct.unpack('<H', data[-2:])[0]
    # 注意：服务器实际发送的 payload 长度可能与 length 字段不一致
    # 使用实际接收到的 payload 进行 CRC 校验
    crc_calc = modbus_crc16(payload)
    if crc_recv != crc_calc:
        print(f"CRC error! calc:{crc_calc:04X} recv:{crc_recv:04X}")
        return None
    seq, encrypt, cmd = struct.unpack('<H B B', payload[:4])
    body = payload[4:]
    return cmd, seq, body


def generate_trans_seq(gun_no: int) -> bytes:
    now = datetime.now()
    ymdhms = now.strftime('%y%m%d%H%M%S').encode()
    incr = int(time.time()) % 65536
    return PILE_SN + bytes([gun_no]) + ymdhms + struct.pack('<H', incr)


def login():
    body = (
            PILE_SN +
            bytes([0x00 if GUN_COUNT == 1 else 0x00]) +  # 桩类型 0=直流
            bytes([GUN_COUNT]) +
            bytes([PROTOCOL_VER]) +
            PROGRAM_VER +
            bytes([NET_TYPE]) +
            SIM_CARD +
            bytes([OPERATOR])
    )
    return build_frame(CMD_LOGIN, body)


def heartbeat():
    status = 0x00  # 正常
    body = PILE_SN + bytes([GUN_NO]) + bytes([status])
    return build_frame(CMD_HEARTBEAT, body)


def pack_bcd_number(value: int, byte_length: int) -> bytes:
    """整数转定长BCD码，高位字节在前"""
    if value < 0:
        raise ValueError("BCD编号不能为负数")

    digits = str(value).zfill(byte_length * 2)

    if len(digits) != byte_length * 2:
        raise ValueError("BCD编号超出长度")

    return bytes.fromhex(digits)


def bill_model_check(model_no: int = 0):
    body = PILE_SN + pack_bcd_number(model_no, 2)
    return build_frame(CMD_BILL_CHECK, body)


def bill_model_request():
    body = PILE_SN
    return build_frame(CMD_BILL_REQUEST, body)


def upload_realtime_data(trans_seq, status, is_gun_back, is_gun_inserted,
                         voltage, current, gun_temp, soc=0, batt_max_temp=0,
                         charge_time=0, remain_time=0, energy=0, loss_energy=0,
                         amount=0, fault=0):
    """上传实时监测数据 0x13"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            bytes([status]) +
            bytes([is_gun_back]) +
            bytes([is_gun_inserted]) +
            struct.pack('<H', voltage) +
            struct.pack('<H', current) +
            bytes([gun_temp]) +
            b'\x00\x00\x00\x00\x00\x00\x00\x00' +  # 枪线编码8字节
            bytes([soc]) +
            bytes([batt_max_temp]) +
            struct.pack('<H', charge_time) +
            struct.pack('<H', remain_time) +
            struct.pack('<I', energy) +
            struct.pack('<I', loss_energy) +
            struct.pack('<I', amount) +
            struct.pack('<H', fault)
    )
    return build_frame(CMD_UPLOAD_REALTIME, body)


def charge_handshake(trans_seq, bms_ver, bms_type, capacity, voltage,
                     battery_maker, battery_sn, year, month, day,
                     charge_count, ownership, vin, bms_soft_ver):
    """充电握手 0x15"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            b'\x00\x01\x01' +  # BMS版本 V1.1
            bytes([bms_type]) +
            struct.pack('<H', capacity) +
            struct.pack('<H', voltage) +
            battery_maker +
            battery_sn +
            bytes([year, month, day]) +
            struct.pack('<I', charge_count)[:3] +  # 充电次数：3字节（小端）
            bytes([ownership]) +
            b'\x00' +  # 预留
            vin +
            bms_soft_ver
    )
    return build_frame(CMD_CHARGE_HANDSHAKE, body)


def param_config(trans_seq, max_voltage, max_current, total_energy,
                 max_total_voltage, max_temp, soc, current_voltage,
                 pile_max_voltage, pile_min_voltage, pile_max_current,
                 pile_min_current):
    """参数配置 0x17"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            struct.pack('<H', max_voltage) +
            struct.pack('<H', max_current) +
            struct.pack('<H', total_energy) +
            struct.pack('<H', max_total_voltage) +
            bytes([max_temp]) +
            struct.pack('<H', soc) +
            struct.pack('<H', current_voltage) +
            struct.pack('<H', pile_max_voltage) +
            struct.pack('<H', pile_min_voltage) +
            struct.pack('<H', pile_max_current) +
            struct.pack('<H', pile_min_current)
    )
    return build_frame(CMD_PARAM_CONFIG, body)


def charge_end(trans_seq, soc, min_voltage, max_voltage, min_temp, max_temp,
               charge_time, output_energy, charger_id):
    """充电结束 0x19"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            bytes([soc]) +
            struct.pack('<H', min_voltage) +
            struct.pack('<H', max_voltage) +
            bytes([min_temp]) +
            bytes([max_temp]) +
            struct.pack('<H', charge_time) +
            struct.pack('<H', output_energy) +
            struct.pack('<I', charger_id)
    )
    return build_frame(CMD_CHARGE_END, body)


def charge_request(start_type, need_pwd, card_no, pwd, vin):
    """主动申请启动充电 0x31"""
    body = (
            PILE_SN +
            bytes([GUN_NO]) +
            bytes([start_type]) +
            bytes([need_pwd]) +
            card_no +
            pwd +
            vin
    )
    return build_frame(CMD_CHARGE_REQUEST, body)


def remote_start_resp(trans_seq, result, reason=0):
    """远程启动充电命令回复 0x33"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            bytes([result]) +
            bytes([reason])
    )
    return build_frame(CMD_REMOTE_START_RESP, body)


def remote_stop_resp(result, reason=0):
    """远程停机命令回复 0x35"""
    body = (
            PILE_SN +
            bytes([GUN_NO]) +
            bytes([result]) +
            bytes([reason])
    )
    return build_frame(CMD_REMOTE_STOP_RESP, body)


def trade_record(trans_seq, start_time, end_time, peak_price, peak_energy,
                 peak_loss, peak_amount, sharp_price, sharp_energy, sharp_loss,
                 sharp_amount, flat_price, flat_energy, flat_loss,
                 flat_amount, valley_price, valley_energy, valley_loss,
                 valley_amount, meter_start, meter_end, total_energy,
                 total_loss, total_amount, vin, trade_type, trade_time,
                 stop_reason, card_no):
    """交易记录 0x3B"""
    body = (
            trans_seq +
            PILE_SN +
            bytes([GUN_NO]) +
            start_time +
            end_time +
            struct.pack('<I', peak_price) +
            struct.pack('<I', peak_energy) +
            struct.pack('<I', peak_loss) +
            struct.pack('<I', peak_amount) +
            struct.pack('<I', sharp_price) +
            struct.pack('<I', sharp_energy) +
            struct.pack('<I', sharp_loss) +
            struct.pack('<I', sharp_amount) +
            struct.pack('<I', flat_price) +
            struct.pack('<I', flat_energy) +
            struct.pack('<I', flat_loss) +
            struct.pack('<I', flat_amount) +
            struct.pack('<I', valley_price) +
            struct.pack('<I', valley_energy) +
            struct.pack('<I', valley_loss) +
            struct.pack('<I', valley_amount) +
            bytes([meter_start & 0xFF]) + struct.pack('<I', (meter_start >> 8) & 0xFFFFFFFF) +
            bytes([meter_end & 0xFF]) + struct.pack('<I', (meter_end >> 8) & 0xFFFFFFFF) +
            struct.pack('<I', total_energy) +
            struct.pack('<I', total_loss) +
            struct.pack('<I', total_amount) +
            vin +
            bytes([trade_type]) +
            trade_time +
            bytes([stop_reason]) +
            card_no
    )
    return build_frame(CMD_TRADE_RECORD, body)


def balance_update_resp(card_no, result):
    """余额更新应答 0x41"""
    body = (
            PILE_SN +
            card_no +
            bytes([result])
    )
    return build_frame(CMD_BALANCE_UPDATE_RESP, body)


def param_set_resp(result):
    """充电桩工作参数设置应答 0x51"""
    body = (
            PILE_SN +
            bytes([result])
    )
    return build_frame(CMD_PARAM_SET_RESP, body)


def time_set_resp(time_bytes):
    """对时设置应答 0x55"""
    body = (
            PILE_SN +
            time_bytes
    )
    return build_frame(CMD_TIME_SET_RESP, body)


def bill_set_resp(result):
    """计费模型应答 0x57"""
    body = (
            PILE_SN +
            bytes([result])
    )
    return build_frame(CMD_BILL_SET_RESP, body)


def remote_restart_resp(result):
    """远程重启应答 0x91"""
    body = (
            PILE_SN +
            bytes([result])
    )
    return build_frame(CMD_REMOTE_RESTART_RESP, body)


def lock_status(gun_no, lock_state, vehicle_state, battery_state, alarm_state):
    """地锁数据上送 0x61"""
    body = (
            PILE_SN +
            bytes([gun_no]) +
            bytes([lock_state]) +
            bytes([vehicle_state]) +
            bytes([battery_state]) +
            bytes([alarm_state]) +
            b'\x00\x00\x00\x00'  # 预留
    )
    return build_frame(CMD_LOCK_STATUS, body)


def lock_ctrl_resp(gun_no, result):
    """地锁控制返回 0x63"""
    body = (
            PILE_SN +
            bytes([gun_no]) +
            bytes([result]) +
            b'\x00\x00\x00\x00'  # 预留
    )
    return build_frame(CMD_LOCK_CTRL_RESP, body)


def pack_cp56time2a(dt):
    """CP56Time2a 时间格式 - 按协议文档修正"""
    # 毫秒 = 秒*1000 + 微秒/1000 (标准CP56Time2a格式)
    ms = dt.second * 1000 + int(dt.microsecond / 1000)
    minute = dt.minute
    hour = dt.hour
    day = dt.day
    month = dt.month
    year = dt.year - 2000  # 年份从2000年起算
    weekday = dt.isoweekday()  # 1=周一, 7=周日
    SU = False  # 夏令时标志
    IV = False  # 无效标志

    # 字节1: 毫秒低8位 (D7-D0)
    b1 = ms & 0xFF
    # 字节2: 毫秒高8位 (D15-D8)
    b2 = (ms >> 8) & 0xFF
    # 字节3: IV(D7) + RES1(D6) + Minutes(D5-D0)
    b3 = (0x80 if IV else 0x00) | (minute & 0x3F)
    # 字节4: SU(D7) + RES2(D6-D5) + Hours(D4-D0)
    b4 = (0x80 if SU else 0x00) | (hour & 0x1F)
    # 字节5: DAY of WEEK(D7-D5) + DAY of MONTH(D4-D0)
    b5 = ((weekday & 0x07) << 5) | (day & 0x1F)
    # 字节6: RES3(D7-D4) + Month(D3-D0)
    b6 = (month & 0x0F)
    # 字节7: RES4(D7) + Years(D6-D0)
    b7 = year & 0x7F

    return bytes([b1, b2, b3, b4, b5, b6, b7])


# 全局变量用于存储充电状态
charging_state = {
    'is_charging': False,
    'trans_seq': b'\x00' * 16,
    'start_time': None,
    'voltage': 0,
    'current': 0,
    'energy': 0,
    'charge_time': 0,
    'amount': 0.0,
    'lock': threading.Lock()
}

# 用于唤醒实时数据上报线程的事件对象
realtime_event = threading.Event()

# 重连相关配置
RECONNECT_BASE_DELAY = 5       # 基础重连等待时间（秒）
RECONNECT_MAX_DELAY = 60       # 最大重连等待时间（秒）
RECONNECT_BACKOFF_FACTOR = 2   # 退避因子

# 共享的 socket 引用（供子线程使用），在线程间传递当前连接
current_sock = [None]  # [sock]
connected = threading.Event()  # 连接就绪事件


def _do_send(frame: bytes):
    """安全发送：通过共享 socket 发送数据，若连接已断则静默忽略"""
    sock = current_sock[0]
    if sock is None or not connected.is_set():
        return
    try:
        with send_lock:
            sock.send(frame)
    except Exception:
        pass  # 主循环会检测断开并重连


def stop_charging_and_report():
    """手动停止充电并上报账单（通过共享 socket 发送）"""
    global charging_state

    with charging_state['lock']:
        if not charging_state['is_charging']:
            print("当前未在充电状态，无需停止")
            return

        charging_state['is_charging'] = False
        realtime_event.set()
        trans_seq = charging_state['trans_seq']
        start_time = charging_state['start_time']
        elapsed_seconds = time.time() - start_time
        charge_time = math.ceil(elapsed_seconds / 60)
        energy = charging_state['energy']

    # 1. 回复停机成功
    _do_send(remote_stop_resp(1, 0))
    print("✓ 手动停机：回复停机成功 (0x35)")

    # 2. 发送充电结束帧 0x19
    if len(trans_seq) == 16 and trans_seq != b'\x00' * 16:
        soc = 80
        min_voltage = 3800
        max_voltage = 4100
        min_temp = 15
        max_temp = 35
        output_energy = int(energy * 10)
        charger_id = int.from_bytes(trans_seq[:4], 'big')

        _do_send(charge_end(
            trans_seq, soc, min_voltage, max_voltage, min_temp, max_temp,
            charge_time, output_energy, charger_id
        ))
        print(f"✓ 充电结束帧已发送 (0x19) | 充电时长: {charge_time}分钟 | 电量: {energy:.2f}度")

    # 3. 上报交易记录 0x3B
    if len(trans_seq) == 16 and trans_seq != b'\x00' * 16:
        now = datetime.now()
        start_dt = now - timedelta(seconds=elapsed_seconds)
        end_dt = now

        start_time_bytes = pack_cp56time2a(start_dt)
        end_time_bytes = pack_cp56time2a(end_dt)
        trade_time_bytes = pack_cp56time2a(now)

        peak_price = 200000
        peak_energy = int(energy * 10000)
        peak_amount = int(peak_energy * peak_price / 100000)
        total_energy = peak_energy
        total_amount = 800

        card_no = b'\xD1\x4B\x0A\x54\x00\x00\x00\x00'
        vin = b'LB37644ZMS0012345'

        _do_send(trade_record(
            trans_seq=trans_seq,
            start_time=start_time_bytes,
            end_time=end_time_bytes,
            peak_price=peak_price, peak_energy=peak_energy,
            peak_loss=0, peak_amount=peak_amount,
            sharp_price=0, sharp_energy=0,
            sharp_loss=0, sharp_amount=0,
            flat_price=0, flat_energy=0,
            flat_loss=0, flat_amount=0,
            valley_price=0, valley_energy=0,
            valley_loss=0, valley_amount=0,
            meter_start=0, meter_end=0,
            total_energy=total_energy, total_loss=0,
            total_amount=total_amount,
            vin=vin, trade_type=TRADE_TYPE_APP,
            trade_time=trade_time_bytes,
            stop_reason=0x40,
            card_no=card_no
        ))
        print(
            f"✓ 上报交易记录 (0x3B): 充电时长={charge_time}分钟, 电量={energy:.2f}度, 金额={total_amount / 10000:.2f}元")


def heartbeat_loop():
    """心跳线程：持续运行，断连时等待重连后恢复"""
    while running_flag:
        connected.wait()
        if not running_flag:
            break
        time.sleep(HEARTBEAT_INTERVAL)
        sock = current_sock[0]
        if sock is None or not connected.is_set():
            continue
        try:
            with send_lock:
                sock.send(heartbeat())
            print("发送心跳 (0x03)")
        except Exception:
            pass  # 连接已断，主循环会检测并重连


def realtime_upload_loop():
    """实时数据上报线程：持续运行，断连时本地数据继续更新，重连后恢复上报"""
    while running_flag:
        if not running_flag:
            break
        try:
            with charging_state['lock']:
                is_charging = charging_state['is_charging']

                if is_charging:
                    charging_state['charge_time'] += 1
                    charging_state['energy'] += 0.5
                    charging_state['amount'] = min(
                        charging_state['amount'] + AMOUNT_INCREMENT,
                        MAX_AMOUNT
                    )

                trans_seq = charging_state['trans_seq']
                charge_time = charging_state['charge_time']
                energy = charging_state['energy']
                voltage = charging_state['voltage']
                current = charging_state['current']
                amount = charging_state['amount']

            if is_charging:
                energy_raw = int(energy * 10000)
                amount_in_cents = int(amount * 10000)

                data = upload_realtime_data(
                    trans_seq, STATUS_CHARGING,
                    is_gun_back=0, is_gun_inserted=1,
                    voltage=voltage, current=current,
                    gun_temp=25,
                    soc=min(int(energy * 5), 100),
                    charge_time=charge_time,
                    remain_time=0,
                    energy=energy_raw,
                    loss_energy=energy_raw,
                    amount=amount_in_cents,
                    fault=0
                )
                timeout = 5
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] 上报实时数据: 充电中 | 时间={charge_time}min, 电量={energy:.2f}度")
            else:
                data = upload_realtime_data(
                    b'\x00' * 16, STATUS_IDLE,
                    is_gun_back=1, is_gun_inserted=1,
                    voltage=0, current=0,
                    gun_temp=0, soc=0,
                    charge_time=0, remain_time=0,
                    energy=0, loss_energy=0,
                    amount=0, fault=0
                )
                timeout = 15
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 上报实时数据: 待机中")

            _do_send(data)

            realtime_event.clear()
            realtime_event.wait(timeout)

        except Exception as e:
            print(f"上报实时数据异常: {e}")
            if not running_flag:
                break
            time.sleep(1)


def input_listener():
    """监听控制台输入，支持手动停止充电"""
    # 启动后短暂延迟，避免和连接日志混在一起
    time.sleep(1)
    print("\n" + "=" * 50)
    print("控制台命令: 输入 'stop' 可手动停止充电并上报账单")
    print("=" * 50 + "\n")

    while running_flag:
        try:
            cmd = input().strip().lower()
            if cmd == 'stop':
                print("→ 收到手动停止命令，开始执行停止流程...")
                stop_charging_and_report()
            elif cmd == '':
                continue
            else:
                print(f"未知命令: '{cmd}'，可用命令: stop")
        except EOFError:
            break
        except Exception as e:
            print(f"输入处理异常: {e}")
            break


def simulate_pile():
    global charging_state, running_flag, current_sock, connected

    running_flag = True
    connected.clear()

    # ========== 启动常驻线程（只启动一次） ==========
    hb_thread = threading.Thread(target=heartbeat_loop, name="Heartbeat", daemon=True)
    hb_thread.start()

    realtime_thread = threading.Thread(target=realtime_upload_loop, name="Realtime", daemon=True)
    realtime_thread.start()

    input_thread = threading.Thread(target=input_listener, name="Input", daemon=True)
    input_thread.start()

    reconnect_delay = RECONNECT_BASE_DELAY  # 当前重连等待时间

    # ========== 重连主循环 ==========
    while running_flag:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        current_sock[0] = sock

        try:
            sock.connect((SERVER_HOST, SERVER_PORT))
            print(f"已连接云平台 {SERVER_HOST}:{SERVER_PORT}")
            connected.set()  # 通知子线程连接就绪
            realtime_event.set()  # 唤醒实时线程立即上报
            reconnect_delay = RECONNECT_BASE_DELAY  # 连接成功后重置退避时间

            # 1. 登录
            with send_lock:
                sock.send(login())
            print("已发送登录帧 (0x01)")

            model_checked = False
            model_requested = False

            # ========== 消息处理循环 ==========
            while True:
                try:
                    data = sock.recv(2048)
                    if not data:
                        print("✗ 服务端关闭了连接")
                        break

                    print(f"← 原始数据: len={len(data)} | hex={data.hex(' ').upper()}")
                    result = parse_frame(data)
                    if result is None:
                        print("✗ 帧解析失败，跳过")
                        continue
                    cmd, seq, body = result

                    print(f"← 收到 {cmd:02X} | seq={seq:04X} | body_len={len(body)} | hex={body.hex().upper()}")

                    if cmd == CMD_LOGIN_RESP:
                        if len(body) >= 8:
                            result = body[7]
                            if result == 0x00:
                                print("✓ 登录成功")

                                # 立即校验计费模型
                                with send_lock:
                                    sock.send(bill_model_check(0))
                            else:
                                print("✗ 登录失败")
                                break

                    elif cmd == CMD_BILL_CHECK_RESP:
                        if len(body) >= 10:
                            result = body[9]
                            if result == 0x00:
                                print("✓ 计费模型一致")
                                model_checked = True
                            else:
                                print("⊗ 计费模型不一致 → 请求新模型")
                                with send_lock:
                                    sock.send(bill_model_request())
                                model_requested = True

                    elif cmd == CMD_BILL_REQUEST_RESP:
                        print("✓ 收到完整计费模型 (0x0A)")
                        if len(body) >= 42:
                            peak_electric = struct.unpack('<I', body[9:13])[0]
                            peak_service = struct.unpack('<I', body[13:17])[0]
                            sharp_electric = struct.unpack('<I', body[17:21])[0]
                            sharp_service = struct.unpack('<I', body[21:25])[0]
                            flat_electric = struct.unpack('<I', body[25:29])[0]
                            flat_service = struct.unpack('<I', body[29:33])[0]
                            valley_electric = struct.unpack('<I', body[33:37])[0]
                            valley_service = struct.unpack('<I', body[37:41])[0]
                            loss_ratio = body[41]

                            print(f"  - 尖电费: {peak_electric / 100000:.2f} 元/度")
                            print(f"  - 尖服务费: {peak_service / 100000:.2f} 元/度")
                            print(f"  - 峰电费: {sharp_electric / 100000:.2f} 元/度")
                            print(f"  - 峰服务费: {sharp_service / 100000:.2f} 元/度")
                            print(f"  - 平电费: {flat_electric / 100000:.2f} 元/度")
                            print(f"  - 平服务费: {flat_service / 100000:.2f} 元/度")
                            print(f"  - 谷电费: {valley_electric / 100000:.2f} 元/度")
                            print(f"  - 谷服务费: {valley_service / 100000:.2f} 元/度")
                            print(f"  - 计损比例: {loss_ratio}")
                        model_checked = True

                    elif cmd == CMD_HEARTBEAT_RESP:
                        print("✓ 心跳应答")

                    elif cmd == CMD_READ_REALTIME:
                        print("← 平台请求实时数据 (0x12)")
                        with charging_state['lock']:
                            status = STATUS_CHARGING if charging_state['is_charging'] else STATUS_IDLE
                            if status == STATUS_IDLE:
                                trans_seq = b'\x00' * 16
                                voltage = 0
                                current = 0
                                gun_temp = 0
                                soc = 0
                                charge_time = 0
                                energy = 0
                            else:
                                trans_seq = charging_state['trans_seq']
                                voltage = charging_state['voltage']
                                current = charging_state['current']
                                gun_temp = 25
                                soc = min(int(charging_state['energy'] * 10), 100)
                                charge_time = charging_state['charge_time']
                                energy = charging_state['energy']

                        with send_lock:
                            sock.send(upload_realtime_data(
                                trans_seq, status,
                                is_gun_back=1, is_gun_inserted=1,
                                voltage=voltage, current=current,
                                gun_temp=gun_temp, soc=soc,
                                charge_time=charge_time, remain_time=0,
                                energy=energy, loss_energy=energy,
                                amount=0, fault=0
                            ))

                    elif cmd == CMD_REMOTE_START_CMD:
                        print("← 收到远程启动充电命令 (0x34)")
                        if len(body) >= 44:
                            trans_seq = body[:16]
                            pile_sn = body[16:23]
                            gun_no = body[23]
                            logic_card_no = body[24:32]
                            physical_card_no = body[32:40]
                            balance = struct.unpack('<I', body[40:44])[0]

                            print(f"  - 交易流水号: {trans_seq.hex().upper()}")
                            print(f"  - 桩编号: {pile_sn.hex().upper()}")
                            print(f"  - 枪号: {gun_no}")
                            print(f"  - 逻辑卡号: {logic_card_no.hex().upper()}")
                            print(f"  - 物理卡号: {physical_card_no.hex().upper()}")
                            print(f"  - 账户余额: {balance / 100:.2f} 元")

                            with send_lock:
                                sock.send(remote_start_resp(trans_seq, 1, 0))
                            print("✓ 回复启动成功")

                            time.sleep(10)
                            print("→ 发送充电握手指令 (0x15)")

                            bms_ver = b'\x00\x01\x01'
                            bms_type = 0x01
                            capacity = 5000
                            voltage = 4000
                            battery_maker = b'CATL'
                            battery_sn = b'\x01\x02\x03\x04'
                            year = 39
                            month = 1
                            day = 1
                            charge_count = 100
                            ownership = 0x01
                            vin = b'LB37644ZMS0012345'
                            bms_soft_ver = b'\x00\x00\xFF\x07\xE0\x01\x01\x01'

                            with send_lock:
                                sock.send(charge_handshake(
                                    trans_seq, bms_ver, bms_type, capacity, voltage,
                                    battery_maker, battery_sn, year, month, day,
                                    charge_count, ownership, vin, bms_soft_ver
                                ))
                            print("✓ 握手指令已发送")
                            time.sleep(5)

                            # 发送参数配置 0x17（握手成功后发送）
                            print("→ 发送参数配置指令 (0x17)")
                            with send_lock:
                                sock.send(param_config(
                                    trans_seq=trans_seq,
                                    max_voltage=2400,        # 24.00V (0.01V/位, 0V偏移)
                                    max_current=5000,         # 100A ((100+400)/0.1, -400A偏移)
                                    total_energy=500,         # 50kWh (0.1kWh/位)
                                    max_total_voltage=4000,   # 400.0V (0.1V/位)
                                    max_temp=85,              # 35℃ (1℃/位, -50℃偏移: 35+50=85)
                                    soc=100,                  # 10.0% (0.1%/位)
                                    current_voltage=3500,     # 350V 整车当前电压
                                    pile_max_voltage=7500,    # 750.0V 桩最高输出电压
                                    pile_min_voltage=2000,    # 200.0V 桩最低输出电压
                                    pile_max_current=5200,    # 120A 桩最大输出电流 ((120+400)/0.1)
                                    pile_min_current=4000,    # 0A 桩最小输出电流 ((0+400)/0.1)
                                ))
                            print("✓ 参数配置指令已发送")
                            time.sleep(5)

                            with charging_state['lock']:
                                charging_state['is_charging'] = True
                                charging_state['trans_seq'] = trans_seq
                                charging_state['start_time'] = time.time()
                                charging_state['voltage'] = voltage
                                charging_state['current'] = 2000
                                charging_state['energy'] = 0
                                charging_state['charge_time'] = 0
                            realtime_event.set()
                            print("✓ 充电状态已更新为：正在充电")
                        else:
                            with send_lock:
                                sock.send(remote_start_resp(b'\x00' * 16, 0, 1))
                            print("✗ 数据长度不足，回复启动失败")

                    elif cmd == CMD_REMOTE_STOP_CMD:
                        print("← 收到远程停机命令 (0x36)")

                        with charging_state['lock']:
                            if charging_state['is_charging']:
                                charging_state['is_charging'] = False
                                realtime_event.set()
                                trans_seq = charging_state['trans_seq']
                                start_time = charging_state['start_time']
                                elapsed_seconds = time.time() - start_time
                                charge_time = math.ceil(elapsed_seconds / 60)
                                energy = charging_state['energy']
                            else:
                                trans_seq = b'\x00' * 16
                                elapsed_seconds = 0
                                charge_time = 0
                                energy = 0

                        with send_lock:
                            sock.send(remote_stop_resp(1, 0))
                        print("✓ 回复停机成功")

                        if len(trans_seq) == 16 and trans_seq != b'\x00' * 16:
                            soc = 100
                            min_voltage = 3800
                            max_voltage = 4100
                            min_temp = 15
                            max_temp = 35
                            output_energy = int(energy * 10)
                            charger_id = int.from_bytes(trans_seq[:4], 'big')

                            with send_lock:
                                sock.send(charge_end(
                                    trans_seq, soc, min_voltage, max_voltage, min_temp, max_temp,
                                    charge_time, output_energy, charger_id
                                ))
                            print(f"✓ 充电结束帧已发送 (0x19) | 充电时长: {charge_time}分钟 | 电量: {energy:.2f}度")

                        if len(trans_seq) == 16 and trans_seq != b'\x00' * 16:
                            now = datetime.now()
                            start_dt = now - timedelta(seconds=elapsed_seconds)
                            end_dt = now

                            start_time_bytes = pack_cp56time2a(start_dt)
                            end_time_bytes = pack_cp56time2a(end_dt)
                            trade_time_bytes = pack_cp56time2a(now)

                            peak_price = 200000
                            peak_energy = int(energy * 10000)
                            peak_amount = int(peak_energy * peak_price / 100000)

                            total_energy = peak_energy
                            total_amount = 800

                            card_no = b'\xD1\x4B\x0A\x54\x00\x00\x00\x00'
                            vin = b'LB37644ZMS0012345'

                            with send_lock:
                                sock.send(trade_record(
                                    trans_seq=trans_seq,
                                    start_time=start_time_bytes,
                                    end_time=end_time_bytes,
                                    peak_price=peak_price, peak_energy=peak_energy,
                                    peak_loss=0, peak_amount=peak_amount,
                                    sharp_price=0, sharp_energy=0,
                                    sharp_loss=0, sharp_amount=0,
                                    flat_price=0, flat_energy=0,
                                    flat_loss=0, flat_amount=0,
                                    valley_price=0, valley_energy=0,
                                    valley_loss=0, valley_amount=0,
                                    meter_start=0, meter_end=0,
                                    total_energy=total_energy, total_loss=0,
                                    total_amount=total_amount,
                                    vin=vin, trade_type=TRADE_TYPE_APP,
                                    trade_time=trade_time_bytes,
                                    stop_reason=0x40,
                                    card_no=card_no
                                ))
                            print(
                                f"✓ 上报交易记录: 充电时长={charge_time}分钟, 电量={energy:.2f}度, 金额={total_amount / 10000:.2f}元")

                    elif cmd == CMD_TRADE_CONFIRM:
                        print("✓ 收到交易记录确认 (0x40)")
                        if len(body) >= 17:
                            result = body[16]
                            if result == 0x00:
                                print("  - 上传成功")
                            else:
                                print("  - 非法账单")

                    elif cmd == CMD_TIME_SET_CMD:
                        print("← 收到对时命令 (0x56)")
                        if len(body) >= 14:
                            pile_sn = body[0:7]
                            time_bytes = body[7:14]
                            print(f"  - 桩编号: {pile_sn.hex().upper()}")
                            print(f"  - 平台时间: {time_bytes.hex().upper()}")
                            with send_lock:
                                sock.send(time_set_resp(time_bytes))
                            print("✓ 回应对时成功")

                    elif cmd == CMD_PARAM_SET_CMD:
                        print("← 收到参数设置命令 (0x52)")
                        if len(body) >= 9:
                            enable_work = body[7]
                            max_power = body[8]
                            print(f"  - 允许工作: {enable_work}")
                            print(f"  - 最大功率: {max_power}%")
                            with send_lock:
                                sock.send(param_set_resp(1))
                            print("✓ 回复参数设置成功")

                    elif cmd == CMD_BILL_SET_CMD:
                        print("← 收到计费模型设置 (0x58)")
                        if len(body) >= 61:
                            peak_price = struct.unpack('<I', body[9:13])[0]
                            flat_price = struct.unpack('<I', body[17:21])[0]
                            valley_price = struct.unpack('<I', body[25:29])[0]
                            print(f"  - 尖费率: {peak_price / 100000:.2f} 元/度")
                            print(f"  - 平费率: {flat_price / 100000:.2f} 元/度")
                            print(f"  - 谷费率: {valley_price / 100000:.2f} 元/度")
                            with send_lock:
                                sock.send(bill_set_resp(1))
                            print("✓ 回复计费模型设置成功")

                    elif cmd == CMD_REMOTE_RESTART_CMD:
                        print("← 收到远程重启命令 (0x92)")
                        if len(body) >= 8:
                            ctrl = body[7]
                            print(f"  - 执行控制: {ctrl}")
                            with send_lock:
                                sock.send(remote_restart_resp(1))
                            print("✓ 回复重启成功 → 断开连接")
                            break  # 模拟重启，主动断开

                    elif cmd == CMD_LOCK_CTRL_CMD:
                        print("← 收到地锁控制命令 (0x62)")
                        if len(body) >= 10:
                            gun_no = body[7]
                            ctrl = body[8]
                            action = "升锁" if ctrl == 0x55 else "降锁"
                            print(f"  - 枪号: {gun_no}")
                            print(f"  - 操作: {action}")
                            with send_lock:
                                sock.send(lock_ctrl_resp(gun_no, 1))
                            print("✓ 回复地锁控制成功")

                except socket.timeout:
                    continue
                except (ConnectionResetError, ConnectionAbortedError,
                        BrokenPipeError, OSError) as e:
                    print(f"✗ 连接断开: {e}")
                    break
                except Exception as e:
                    print(f"✗ 异常: {e}")
                    break

        except Exception as e:
            print(f"✗ 连接/运行异常: {e}")
        finally:
            # 标记断开连接
            connected.clear()
            current_sock[0] = None
            try:
                sock.close()
            except Exception:
                pass

            # 断连不重置充电状态，桩继续在本地充电
            with charging_state['lock']:
                if charging_state['is_charging']:
                    print("⚠ 网络断开，本地充电继续，待重连后恢复实时数据上报")
            realtime_event.set()

        # ========== 判断是否继续重连 ==========
        if not running_flag:
            break

        print(f"连接断开，{reconnect_delay}秒后重连...")
        # 分片等待，以便及时响应 running_flag 变化
        for _ in range(reconnect_delay):
            if not running_flag:
                break
            time.sleep(1)

        # 指数退避：每次重连失败后延迟翻倍，但不超过最大值
        reconnect_delay = min(reconnect_delay * RECONNECT_BACKOFF_FACTOR, RECONNECT_MAX_DELAY)

    # ========== 清理 ==========
    running_flag = False
    connected.set()  # 唤醒所有等待 connected 的线程
    realtime_event.set()  # 唤醒实时数据线程
    print("程序已退出")


def pile_code_to_bcd(code: str) -> bytes:
    """14位数字桩编码 → 7字节 BCD"""
    if len(code) != 14 or not code.isdigit():
        raise SystemExit(f"桩编码必须是14位数字: {code}")
    return bytes.fromhex(code)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="云快充协议充电桩模拟器（单桩）")
    parser.add_argument("--host", default=SERVER_HOST, help="云平台地址，默认 %(default)s")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="云平台端口，默认 %(default)s")
    parser.add_argument("--pile", default=PILE_SN.hex().upper(), help="14位数字桩编码，默认 %(default)s")
    parser.add_argument("--guns", type=int, default=GUN_COUNT, help="枪数，默认 %(default)s")
    parser.add_argument("--gun", type=int, default=GUN_NO, help="当前模拟枪号，默认 %(default)s")
    args = parser.parse_args()

    SERVER_HOST = args.host
    SERVER_PORT = args.port
    PILE_SN = pile_code_to_bcd(args.pile)
    GUN_COUNT = args.guns
    GUN_NO = args.gun

    simulate_pile()
