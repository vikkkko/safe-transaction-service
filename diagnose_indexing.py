#!/usr/bin/env python
"""
Safe Transaction Service 索引诊断脚本
用于诊断为什么 SafeContract 表为空
"""

import os
import sys
import django

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from django.conf import settings
from safe_transaction_service.history.models import (
    SafeMasterCopy, ProxyFactory, SafeContract, IndexingStatus, IndexingStatusType
)
from safe_eth.eth import get_auto_ethereum_client
from celery import Celery
from django_celery_beat.models import PeriodicTask


def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)


def check_database_status():
    print_section("1. 数据库状态检查")

    # 检查 SafeMasterCopy
    master_copies = SafeMasterCopy.objects.all()
    print(f"\n✓ SafeMasterCopy 数量: {master_copies.count()}")
    for mc in master_copies:
        print(f"  - 地址: {mc.address}")
        print(f"    版本: {mc.version}")
        print(f"    起始区块: {mc.initial_block_number}")
        print(f"    当前索引到区块: {mc.tx_block_number}")

    # 检查 ProxyFactory
    proxy_factories = ProxyFactory.objects.all()
    print(f"\n✓ ProxyFactory 数量: {proxy_factories.count()}")
    for pf in proxy_factories:
        print(f"  - 地址: {pf.address}")
        print(f"    起始区块: {pf.initial_block_number}")
        print(f"    当前索引到区块: {pf.tx_block_number}")

    # 检查 SafeContract
    safe_contracts = SafeContract.objects.all()
    print(f"\n{'✗' if safe_contracts.count() == 0 else '✓'} SafeContract 数量: {safe_contracts.count()}")
    if safe_contracts.count() > 0:
        print("  最近 5 个 Safe:")
        for sc in safe_contracts.order_by('-created')[:5]:
            print(f"  - {sc.address}")

    # 检查索引状态
    print("\n✓ 索引状态:")
    for status_type in IndexingStatusType:
        try:
            status = IndexingStatus.objects.get(indexing_type=status_type.value)
            print(f"  - {status_type.name}: 区块 {status.block_number}")
        except IndexingStatus.DoesNotExist:
            print(f"  - {status_type.name}: 未初始化")


def check_ethereum_connection():
    print_section("2. 以太坊节点连接检查")

    print(f"\n配置的节点:")
    print(f"  - ETHEREUM_NODE_URL: {settings.ETHEREUM_NODE_URL}")
    print(f"  - ETHEREUM_TRACING_NODE_URL: {getattr(settings, 'ETHEREUM_TRACING_NODE_URL', 'N/A')}")

    try:
        ethereum_client = get_auto_ethereum_client()
        current_block = ethereum_client.current_block_number
        network = ethereum_client.get_network()
        chain_id = ethereum_client.get_chain_id()

        print(f"\n✓ 节点连接成功")
        print(f"  - 网络: {network.name}")
        print(f"  - Chain ID: {chain_id}")
        print(f"  - 当前区块: {current_block}")

        return ethereum_client, current_block

    except Exception as e:
        print(f"\n✗ 节点连接失败: {e}")
        return None, None


def check_celery_tasks():
    print_section("3. Celery 定时任务检查")

    # 检查定时任务配置
    indexing_tasks = [
        'safe_transaction_service.history.tasks.index_new_proxies_task',
        'safe_transaction_service.history.tasks.index_internal_txs_task',
        'safe_transaction_service.history.tasks.index_safe_events_task',
    ]

    print("\n关键索引任务:")
    for task_name in indexing_tasks:
        try:
            task = PeriodicTask.objects.get(task=task_name)
            status = "✓ 已启用" if task.enabled else "✗ 已禁用"
            print(f"  {status} {task.name}")
            if task.interval:
                print(f"      间隔: 每 {task.interval.every} {task.interval.period}")
            if task.crontab:
                print(f"      Cron: {task.crontab}")
        except PeriodicTask.DoesNotExist:
            print(f"  ✗ 未找到任务: {task_name}")


def check_network_type():
    print_section("4. 网络类型检查")

    is_l2 = getattr(settings, 'ETH_L2_NETWORK', False)
    print(f"\nETH_L2_NETWORK: {is_l2}")

    if is_l2:
        print("\n当前配置为 L2 网络模式")
        print("  - index_new_proxies_task 应该启用（每15秒）")
        print("  - index_safe_events_task 应该启用（每5秒）")
        print("  - index_internal_txs_task 应该禁用")
    else:
        print("\n当前配置为主网/L1 模式")
        print("  - index_internal_txs_task 应该启用（每5秒）")
        print("  - index_new_proxies_task 应该禁用")
        print("  - index_safe_events_task 应该禁用")


def analyze_block_range(ethereum_client, current_block):
    print_section("5. 区块范围分析")

    if not ethereum_client:
        print("\n✗ 无法分析，以太坊节点未连接")
        return

    master_copies = SafeMasterCopy.objects.all()
    proxy_factories = ProxyFactory.objects.all()

    if master_copies.count() == 0 and proxy_factories.count() == 0:
        print("\n✗ 没有配置 SafeMasterCopy 或 ProxyFactory")
        return

    print(f"\n当前区块链高度: {current_block}")

    if master_copies.count() > 0:
        min_mc_block = master_copies.order_by('initial_block_number').first().initial_block_number
        max_mc_indexed = master_copies.order_by('-tx_block_number').first().tx_block_number or 0
        blocks_to_scan = current_block - max_mc_indexed

        print(f"\nSafeMasterCopy 索引状态:")
        print(f"  - 最早起始区块: {min_mc_block}")
        print(f"  - 已索引到区块: {max_mc_indexed}")
        print(f"  - 待扫描区块数: {blocks_to_scan}")

        if blocks_to_scan > 1000000:
            print(f"  ⚠️  警告: 需要扫描 {blocks_to_scan} 个区块，这可能需要很长时间")

    if proxy_factories.count() > 0:
        min_pf_block = proxy_factories.order_by('initial_block_number').first().initial_block_number
        max_pf_indexed = proxy_factories.order_by('-tx_block_number').first().tx_block_number or 0
        blocks_to_scan = current_block - max_pf_indexed

        print(f"\nProxyFactory 索引状态:")
        print(f"  - 最早起始区块: {min_pf_block}")
        print(f"  - 已索引到区块: {max_pf_indexed}")
        print(f"  - 待扫描区块数: {blocks_to_scan}")

        if blocks_to_scan > 1000000:
            print(f"  ⚠️  警告: 需要扫描 {blocks_to_scan} 个区块，这可能需要很长时间")


def provide_recommendations():
    print_section("6. 建议和后续步骤")

    safe_count = SafeContract.objects.count()

    if safe_count == 0:
        print("\n【问题诊断】SafeContract 表为空\n")

        # 检查可能的原因
        reasons = []

        # 1. Celery worker 是否运行
        print("请检查以下几点：\n")

        print("1️⃣  Celery Worker 是否运行？")
        print("   执行: docker-compose ps")
        print("   应该看到 indexer-worker 和 scheduler 容器在运行\n")

        print("2️⃣  查看 Celery 日志是否有错误？")
        print("   执行: docker-compose logs -f indexer-worker")
        print("   执行: docker-compose logs -f scheduler\n")

        print("3️⃣  手动触发索引任务测试：")
        print("   # 进入容器")
        print("   docker-compose exec web python manage.py shell\n")
        print("   # 手动运行索引")
        if getattr(settings, 'ETH_L2_NETWORK', False):
            print("   from safe_transaction_service.history.tasks import index_new_proxies_task")
            print("   result = index_new_proxies_task.delay()")
            print("   print(result.get(timeout=60))")
        else:
            print("   from safe_transaction_service.history.tasks import index_internal_txs_task")
            print("   result = index_internal_txs_task.delay()")
            print("   print(result.get(timeout=60))")

        print("\n4️⃣  如果你想快速测试，可以手动添加一个已知的 Safe：")
        print("   from safe_transaction_service.history.models import SafeContract")
        print("   # 替换为一个真实的 Safe 地址")
        print("   SafeContract.objects.create(")
        print("       address='0x...',  # 真实的 Safe 地址")
        print("       ethereum_tx_id='0x...'  # 创建该 Safe 的交易哈希")
        print("   )")

        print("\n5️⃣  查看 API 索引状态：")
        print("   curl http://localhost:8000/api/v1/about/indexing/")

        print("\n6️⃣  如果区块范围太大（几百万个区块），索引需要很长时间")
        print("   考虑调整起始区块号到更近的区块：")
        print("   # 进入 Django shell")
        print("   docker-compose exec web python manage.py shell")
        print("   from safe_transaction_service.history.models import ProxyFactory, SafeMasterCopy")
        print("   # 设置一个更近的起始区块（例如最近10000个区块）")
        print("   from safe_eth.eth import get_auto_ethereum_client")
        print("   ec = get_auto_ethereum_client()")
        print("   recent_block = ec.current_block_number - 10000")
        print("   ProxyFactory.objects.all().update(tx_block_number=recent_block)")
        print("   SafeMasterCopy.objects.all().update(tx_block_number=recent_block)")
    else:
        print(f"\n✓ 系统正常，已发现 {safe_count} 个 Safe 合约")


def main():
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║        Safe Transaction Service - 索引诊断工具                             ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

    # 执行所有检查
    check_database_status()
    ethereum_client, current_block = check_ethereum_connection()
    check_celery_tasks()
    check_network_type()
    analyze_block_range(ethereum_client, current_block)
    provide_recommendations()

    print("\n" + "="*80)
    print("  诊断完成")
    print("="*80 + "\n")


if __name__ == '__main__':
    main()
