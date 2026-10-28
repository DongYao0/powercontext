# 测试与审计记录

## GoalFlow

| 项目 | 修改前 | 修改后 |
|---|---:|---:|
| Issue #213 目标测试 | 11 failed, rc=1 | 11 passed, rc=0 |
| 后端完整测试 | 1870 passed, rc=0 | 1881 passed, rc=0 |
| 前端测试 | — | 14 files / 156 passed |
| `scripts/check.sh` | — | rc=0，无跳过 |
| `scripts/test.sh` | — | rc=0，无跳过 |
| `check-generated-types.sh` | — | rc=0 |

## 稳定性

三个曾失败文件在基线和实现分支各运行 5 轮，共 10/10 全绿；无空响应体、无 ProactorEventLoop 错误、无残留端口或临时数据库增长。全量测试的偶发失败可在两个分支复现，根因是 Windows 中文 locale 下 UTF-8/GBK 子进程输出解码，不归因于本 Issue。

## 变更边界

未改 manifest 写入侧、Context Assembler、迁移、模型、检索排序、预算分配、Agent 注入行为或既有测试断言。
