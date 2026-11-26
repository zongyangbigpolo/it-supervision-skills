# 示例：XX市智慧政务一体化平台（虚构数据）

> 本示例全部单位、人员、金额、序列号均为**虚构**，仅用于演示 skill 的输入与输出。

在本目录下执行：

```bash
CORE=../../skills/it-supervision-core/scripts
python3 $CORE/next_doc_no.py --type TZ --dry-run                     # 预览下一个通知单编号
python3 $CORE/validate_doc.py 监理资料/03-监理通知单/JL-ZHZW-TZ-2026-001_监理通知单_20261126.md --final
python3 $CORE/md_to_docx.py 监理资料/03-监理通知单/JL-ZHZW-TZ-2026-001_监理通知单_20261126.md -o 监理资料/正式件/
python3 ../../skills/hardware-arrival-check/scripts/compare_delivery.py 输入资料/合同设备清单.csv 输入资料/第1批到货清单.csv
```

比对脚本会发现：交换机型号与合同不一致、1 个重复序列号、1 台加电异常。
