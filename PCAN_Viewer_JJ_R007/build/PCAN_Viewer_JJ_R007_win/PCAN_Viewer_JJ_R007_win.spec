# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['d:\\Project\\.Common\\Test\\PCAN_Viewer_JJ\\PCAN_Viewer_JJ_R007\\main.py'],
    pathex=['d:\\Project\\.Common\\Test\\PCAN_Viewer_JJ\\PCAN_Viewer_JJ_R007'],
    binaries=[('d:\\Project\\.Common\\Test\\PCAN_Viewer_JJ\\PCAN_Viewer_JJ_R007\\src\\PCANBasic.dll', '.')],
    datas=[('d:\\Project\\.Common\\Test\\PCAN_Viewer_JJ\\PCAN_Viewer_JJ_R007\\icon', 'icon')],
    hiddenimports=['can.interfaces', 'can.interfaces.canalystii', 'can.interfaces.cantact', 'can.interfaces.gs_usb', 'can.interfaces.ics_neovi', 'can.interfaces.ics_neovi.neovi_bus', 'can.interfaces.iscan', 'can.interfaces.ixxat', 'can.interfaces.ixxat.canlib', 'can.interfaces.ixxat.canlib_vcinpl', 'can.interfaces.ixxat.canlib_vcinpl2', 'can.interfaces.ixxat.constants', 'can.interfaces.ixxat.exceptions', 'can.interfaces.ixxat.structures', 'can.interfaces.kvaser', 'can.interfaces.kvaser.canlib', 'can.interfaces.kvaser.constants', 'can.interfaces.kvaser.structures', 'can.interfaces.neousys', 'can.interfaces.neousys.neousys', 'can.interfaces.nican', 'can.interfaces.nixnet', 'can.interfaces.pcan', 'can.interfaces.pcan.basic', 'can.interfaces.pcan.pcan', 'can.interfaces.robotell', 'can.interfaces.seeedstudio', 'can.interfaces.seeedstudio.seeedstudio', 'can.interfaces.serial', 'can.interfaces.serial.serial_can', 'can.interfaces.slcan', 'can.interfaces.socketcan', 'can.interfaces.socketcan.constants', 'can.interfaces.socketcan.socketcan', 'can.interfaces.socketcan.utils', 'can.interfaces.socketcand', 'can.interfaces.socketcand.socketcand', 'can.interfaces.systec', 'can.interfaces.systec.constants', 'can.interfaces.systec.exceptions', 'can.interfaces.systec.structures', 'can.interfaces.systec.ucan', 'can.interfaces.systec.ucanbus', 'can.interfaces.udp_multicast', 'can.interfaces.udp_multicast.bus', 'can.interfaces.udp_multicast.utils', 'can.interfaces.vector', 'can.interfaces.vector.canlib', 'can.interfaces.vector.exceptions', 'can.interfaces.vector.xlclass', 'can.interfaces.vector.xldefine', 'can.interfaces.vector.xldriver', 'can.interfaces.virtual', 'cantools'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PCAN_Viewer_JJ_R007_win',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['d:\\Project\\.Common\\Test\\PCAN_Viewer_JJ\\PCAN_Viewer_JJ_R007\\icon\\viewer.ico'],
)
