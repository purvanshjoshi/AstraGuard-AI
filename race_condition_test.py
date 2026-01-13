#!/usr/bin/env python3
"""
Test script to reproduce the race condition in async_timeout decorator.

This script creates multiple concurrent calls that timeout and monitors
for uncancelled tasks accumulating in the event loop.
"""

import asyncio
import gc
import sys
import os

# Add current directory to path to import directly
sys.path.insert(0, os.path.dirname(__file__))

# Import from core.timeout_handler
from core.timeout_handler import async_timeout, TimeoutError as CustomTimeoutError

async def slow_operation(delay: float = 1.0):
    """A slow async operation that will timeout"""
    await asyncio.sleep(delay)
    return f"completed after {delay}s"

async def fast_operation():
    """A fast operation that completes before timeout"""
    await asyncio.sleep(0.1)
    return "fast completion"

@async_timeout(seconds=0.5)
async def timeout_operation():
    """Operation that will always timeout"""
    return await slow_operation(2.0)

@async_timeout(seconds=1.0)
async def success_operation():
    """Operation that completes successfully"""
    return await fast_operation()

async def run_concurrent_timeouts(num_tasks: int = 100):
    """Run multiple timeout operations concurrently"""
    tasks = []
    for i in range(num_tasks):
        task = asyncio.create_task(timeout_operation())
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    timeout_count = sum(1 for r in results if isinstance(r, CustomTimeoutError))
    print(f"Completed {num_tasks} timeout tasks, {timeout_count} timed out as expected")

async def run_mixed_operations(num_tasks: int = 100):
    """Run mix of timeout and success operations"""
    tasks = []
    for i in range(num_tasks):
        if i % 2 == 0:
            task = asyncio.create_task(timeout_operation())
        else:
            task = asyncio.create_task(success_operation())
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    timeout_count = sum(1 for r in results if isinstance(r, CustomTimeoutError))
    success_count = sum(1 for r in results if isinstance(r, str) and "completed" in r)
    print(f"Mixed operations: {timeout_count} timeouts, {success_count} successes")

def count_pending_tasks():
    """Count pending tasks in the event loop"""
    try:
        loop = asyncio.get_running_loop()
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        return len(pending)
    except RuntimeError:
        # No running loop
        return 0

async def monitor_resources(duration: int = 30):
    """Monitor task accumulation over time"""
    print("Monitoring task accumulation for race condition...")
    print("Time(s)\tPending Tasks")

    for i in range(duration):
        pending = count_pending_tasks()
        print(f"{i+1}\t\t{pending}")

        # Force garbage collection to see if tasks are cleaned up
        gc.collect()

        await asyncio.sleep(1)

async def main():
    print("Starting race condition test...")

    # Initial state
    initial_tasks = count_pending_tasks()
    print(f"Initial: Tasks={initial_tasks}")

    # Run concurrent timeouts
    print("\nRunning concurrent timeout operations...")
    await run_concurrent_timeouts(50)

    # Check after timeouts
    after_timeout_tasks = count_pending_tasks()
    print(f"After timeouts: Tasks={after_timeout_tasks}")

    # Run mixed operations
    print("\nRunning mixed operations...")
    await run_mixed_operations(50)

    # Check after mixed
    after_mixed_tasks = count_pending_tasks()
    print(f"After mixed: Tasks={after_mixed_tasks}")

    # Monitor for accumulation
    print("\nMonitoring for task accumulation...")
    await monitor_resources(10)

    # Final check
    final_tasks = count_pending_tasks()
    print(f"\nFinal: Tasks={final_tasks}")

    # Check for task accumulation
    task_increase = final_tasks - initial_tasks

    if task_increase > 5:
        print(f"⚠️  POTENTIAL RACE CONDITION: Tasks +{task_increase}")
    else:
        print("✅ No significant task accumulation detected")

if __name__ == "__main__":
    asyncio.run(main())
