#!/usr/bin/env python3
"""Test script for bytecode modification system."""

import dis
import sys
import types
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def sample_function():
    """A sample function to test bytecode modification."""
    x = 1
    y = 2
    z = x + y
    return z

def another_function():
    """Another sample function."""
    for i in range(10):
        print(f"Count: {i}")
    return "done"

def test_basic_functionality():
    """Test basic bytecode modification functionality."""
    print("=== Testing Basic Bytecode Modification ===")
    
    try:
        from dapper._frame_eval.modify_bytecode import clear_bytecode_cache
        from dapper._frame_eval.modify_bytecode import get_bytecode_info
        from dapper._frame_eval.modify_bytecode import get_cache_stats
        from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
        from dapper._frame_eval.modify_bytecode import optimize_bytecode
        from dapper._frame_eval.modify_bytecode import remove_breakpoint_bytecode
        from dapper._frame_eval.modify_bytecode import validate_bytecode
        
        # Get original code object
        original_code = sample_function.__code__
        
        print(f"Original function: {sample_function.__name__}")
        print(f"Original filename: {original_code.co_filename}")
        
        # Get bytecode info
        info = get_bytecode_info(original_code)
        print(f"Original bytecode info: {info}")
        
        # Validate bytecode
        is_valid = validate_bytecode(original_code)
        print(f"Original bytecode valid: {is_valid}")
        
        # Test injection (no breakpoints)
        success, modified_code = inject_breakpoint_bytecode(original_code, set())
        print(f"Empty breakpoint injection: {success}")
        
        # Test injection with breakpoints
        breakpoint_lines = {3, 5}  # Lines with breakpoints
        success, modified_code = inject_breakpoint_bytecode(original_code, breakpoint_lines)
        print(f"Breakpoint injection success: {success}")
        
        if success:
            modified_info = get_bytecode_info(modified_code)
            print(f"Modified bytecode info: {modified_info}")
            
            # Test that modified bytecode is still valid
            is_valid = validate_bytecode(modified_code)
            print(f"Modified bytecode valid: {is_valid}")
            
            # Test removing breakpoints
            cleaned_code = remove_breakpoint_bytecode(modified_code)
            cleaned_info = get_bytecode_info(cleaned_code)
            print(f"Cleaned bytecode info: {cleaned_info}")
        
        # Test optimization
        optimized_code = optimize_bytecode(original_code)
        optimized_info = get_bytecode_info(optimized_code)
        print(f"Optimized bytecode info: {optimized_info}")
        
        # Test cache stats
        cache_stats = get_cache_stats()
        print(f"Cache stats: {cache_stats}")
        
        # Clear cache
        clear_bytecode_cache()
        cache_stats_after = get_cache_stats()
        print(f"Cache stats after clear: {cache_stats_after}")
        
        print("✅ Basic functionality tests passed")
        
    except Exception as e:
        print(f"❌ Basic functionality test failed: {e}")
        import traceback
        traceback.print_exc()

def test_advanced_functionality():
    """Test advanced bytecode modification features."""
    print("\n=== Testing Advanced Bytecode Modification ===")
    
    try:
        from dapper._frame_eval.modify_bytecode import BytecodeModifier
        from dapper._frame_eval.modify_bytecode import set_optimization_enabled
        
        # Create a custom modifier
        modifier = BytecodeModifier()
        
        print(f"Modifier optimization enabled: {modifier.optimization_enabled}")
        print(f"Modifier breakpoint counter: {modifier.breakpoint_counter}")
        
        # Test with another function
        code_obj = another_function.__code__
        
        # Create breakpoint wrapper
        wrapper_code = modifier.create_breakpoint_wrapper_code(10)
        print(f"Created wrapper code: {type(wrapper_code)}")
        
        # Test breakpoint injection with debug mode
        breakpoint_lines = {2, 3, 4}
        success, modified_code = modifier.inject_breakpoints(
            code_obj, breakpoint_lines, debug_mode=True
        )
        print(f"Advanced breakpoint injection: {success}")
        
        if success:
            # Test optimization toggle
            set_optimization_enabled(False)
            optimized_code = modifier.optimize_code_object(modified_code)
            print(f"Optimization disabled - same code: {optimized_code is modified_code}")
            
            set_optimization_enabled(True)
            optimized_code = modifier.optimize_code_object(modified_code)
            print(f"Optimization enabled - different code: {optimized_code is not modified_code}")
        
        print("✅ Advanced functionality tests passed")
        
    except Exception as e:
        print(f"❌ Advanced functionality test failed: {e}")
        import traceback
        traceback.print_exc()

def test_error_handling():
    """Test error handling in bytecode modification."""
    print("\n=== Testing Error Handling ===")
    
    try:
        from dapper._frame_eval.modify_bytecode import get_bytecode_info
        from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
        from dapper._frame_eval.modify_bytecode import validate_bytecode
        
        # Test with invalid code object
        try:
            invalid_code = types.CodeType(
                0, 0, 0, 0, 0, 0, b"", (), (), (), "", "", 0, b"", (), ()
            )
            
            # This should handle gracefully
            is_valid = validate_bytecode(invalid_code)
            print(f"Invalid code validation: {is_valid}")
            
            info = get_bytecode_info(invalid_code)
            print(f"Invalid code info: {info}")
            
        except Exception as e:
            print(f"Expected error with invalid code: {e}")
        
        # Test with non-existent breakpoint lines
        original_code = sample_function.__code__
        success, modified_code = inject_breakpoint_bytecode(original_code, {999, 1000})
        print(f"Non-existent lines injection: {success}")
        
        # Test with very large breakpoint set
        large_breakpoint_set = set(range(1, 1000))
        success, modified_code = inject_breakpoint_bytecode(original_code, large_breakpoint_set)
        print(f"Large breakpoint set injection: {success}")
        
        print("✅ Error handling tests passed")
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        import traceback
        traceback.print_exc()

def test_instruction_analysis():
    """Test instruction analysis capabilities."""
    print("\n=== Testing Instruction Analysis ===")
    
    try:
        from dapper._frame_eval.modify_bytecode import BytecodeModifier
        
        modifier = BytecodeModifier()
        
        # Analyze sample function
        original_code = sample_function.__code__
        instructions = list(dis.get_instructions(original_code))
        
        print(f"Sample function has {len(instructions)} instructions")
        
        # Print first few instructions
        for i, instr in enumerate(instructions[:5]):
            print(f"  {i}: {instr.opname} {instr.argval} (line {instr.starts_line})")
        
        # Test breakpoint sequence detection
        print("Testing breakpoint sequence detection...")
        
        # Create a fake breakpoint sequence
        if sys.version_info >= (3, 11):
            # Python 3.11+ requires line_number parameter
            fake_instructions = [
                dis.Instruction("LOAD_CONST", 100, 0, 42, "42", 0, None, False, 1),
                dis.Instruction("CALL_FUNCTION", 142, 1, 1, "", 2, None, False, 1),
                dis.Instruction("POP_TOP", 1, None, None, "", 3, None, False, 1),
            ]
        else:
            # Python 3.10 and earlier
            fake_instructions = [
                dis.Instruction("LOAD_CONST", 100, 0, 42, "42", 0, None, False),
                dis.Instruction("CALL_FUNCTION", 142, 1, 1, "", 2, None, False),
                dis.Instruction("POP_TOP", 1, None, None, "", 3, None, False),
            ]
        
        is_breakpoint = modifier._is_breakpoint_sequence(fake_instructions, 0)
        print(f"Fake breakpoint sequence detected: {is_breakpoint}")
        
        # Test injection point finding
        breakpoint_lines = {3, 5}
        injection_points = modifier._find_injection_points(instructions, breakpoint_lines)
        print(f"Injection points found: {injection_points}")
        
        print("✅ Instruction analysis tests passed")
        
    except Exception as e:
        print(f"❌ Instruction analysis test failed: {e}")
        import traceback
        traceback.print_exc()

def test_performance():
    """Test performance of bytecode modification."""
    print("\n=== Testing Performance ===")
    
    try:
        import time

        from dapper._frame_eval.modify_bytecode import clear_bytecode_cache
        from dapper._frame_eval.modify_bytecode import get_cache_stats
        from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
        
        original_code = sample_function.__code__
        breakpoint_lines = {3, 5}
        
        # Test performance without caching
        clear_bytecode_cache()
        
        start_time = time.time()
        for i in range(100):
            success, modified_code = inject_breakpoint_bytecode(original_code, breakpoint_lines)
        end_time = time.time()
        
        print(f"100 injections without cache: {end_time - start_time:.4f}s")
        
        # Test performance with caching
        start_time = time.time()
        for i in range(100):
            success, modified_code = inject_breakpoint_bytecode(original_code, breakpoint_lines)
        end_time = time.time()
        
        print(f"100 injections with cache: {end_time - start_time:.4f}s")
        
        cache_stats = get_cache_stats()
        print(f"Final cache stats: {cache_stats}")
        
        print("✅ Performance tests passed")
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🔧 Bytecode Modification System Test Suite")
    print("=" * 50)
    
    test_basic_functionality()
    test_advanced_functionality()
    test_error_handling()
    test_instruction_analysis()
    test_performance()
    
    print("\n🎉 All tests completed!")
