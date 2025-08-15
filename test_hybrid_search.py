#!/usr/bin/env python3
"""
Test script to verify the hybrid search detection for the 'Kundeling archives' fix.
"""

import re
import unicodedata

def is_latin(text):
    """Function to evaluate whether a piece of text is all Latin characters, numbers or punctuation."""
    return all(
        [
            (
                "LATIN" in unicodedata.name(x)
                or unicodedata.category(x).startswith("P")
                or unicodedata.category(x).startswith("N")
                or unicodedata.category(x).startswith("Z")
            )
            for x in text
        ]
    )

def looks_like_id(text):
    """Current function to evaluate whether a piece of text looks like an identifier."""
    if not text:
        return False
    
    text = text.strip()
    
    # Full pattern: KCDC_A-005
    if re.match(r'^[A-Z]+_[A-Z]-\d+$', text, re.IGNORECASE):
        return True
    
    # Partial pattern ending with single letter: KCDC_A
    if re.match(r'^[A-Z]+_[A-Z]$', text, re.IGNORECASE):
        return True
    
    # Partial pattern starting with single letter and hyphen: A-005, B-005
    if re.match(r'^[A-Z]-\d+$', text, re.IGNORECASE):
        return True
    
    # Pattern for codes that might contain stop words: KCDC_A, ABCD_A, etc.
    if re.match(r'^[A-Z]+_[A-Z]+$', text, re.IGNORECASE) and len(text.split('_')[-1]) == 1:
        return True
    
    return False

def should_use_hybrid_search(text):
    """New function to determine if a search pattern might benefit from hybrid search approach."""
    if not text or len(text.strip()) == 0:
        return False
    
    text = text.strip()
    words = text.split()
    
    # If it's a single word, let full-text search handle it
    if len(words) <= 1:
        return False
    
    # If it looks like an ID pattern, don't use hybrid (handled by looks_like_id)
    if looks_like_id(text):
        return False
    
    # Use hybrid search for multi-word patterns that might contain:
    # 1. Proper nouns (capitalized words that might not be in dictionaries)
    # 2. Mixed content (words + numbers)
    # 3. Complex patterns with symbols
    
    has_proper_nouns = any(word[0].isupper() and word[1:].islower() for word in words if len(word) > 1)
    has_numbers = any(re.search(r'\d', word) for word in words)
    has_symbols = any(re.search(r'[^\w\s]', word) for word in words)
    has_long_words = any(len(word) > 8 for word in words)  # Potentially uncommon words
    
    # Use hybrid search if pattern has characteristics that might cause full-text search issues
    return has_proper_nouns or (has_numbers and len(words) > 2) or has_symbols or has_long_words

def test_patterns():
    """Test different search patterns with the new hybrid search detection."""
    
    test_patterns = [
        "Kundeling archives ID 108 (012 1-1/#/11/7/4)",
        "Kundeling archives",
        "Kundeling archives ID 108", 
        "archives ID 108",
        "ID 108",
        "Kundeling",
        "KCDC_A-005",  # Known working pattern
        "KCDC_B-005",  # Known working pattern
        "John Smith",  # Proper nouns
        "simple search",  # Simple words
        "test",  # Single word
    ]
    
    print("Hybrid Search Detection Analysis:")
    print("=" * 60)
    
    for pattern in test_patterns:
        is_id_like = looks_like_id(pattern)
        is_latin_text = is_latin(pattern)
        use_hybrid = should_use_hybrid_search(pattern)
        
        print(f"Pattern: '{pattern}'")
        print(f"  - looks_like_id(): {is_id_like}")
        print(f"  - is_latin(): {is_latin_text}")
        print(f"  - should_use_hybrid_search(): {use_hybrid}")
        
        # Predict which search path will be taken
        if is_id_like:
            search_method = "EXACT MATCH (icontains)"
        elif use_hybrid:
            search_method = "HYBRID SEARCH (full-text OR word-by-word)"
        elif is_latin_text:
            search_method = "FULL-TEXT SEARCH (SearchQuery)"
        else:
            search_method = "SPLIT WORDS (icontains on each word)"
        
        print(f"  - Search method: {search_method}")
        
        # Show the hybrid search strategy
        if use_hybrid:
            words = pattern.split()
            print(f"  - Will try full-text search for: '{pattern}'")
            print(f"  - Will also try word-by-word search for: {words}")
        
        print()

def test_specific_cases():
    """Test the specific cases mentioned in the bug report."""
    
    print("Specific Bug Cases Analysis:")
    print("=" * 60)
    
    failing_cases = [
        "Kundeling archives ID 108 (012 1-1/#/11/7/4)",
        "Kundeling archives",
        "Kundeling archives ID 108"
    ]
    
    working_cases = [
        "archives ID 108",
        "ID 108"
    ]
    
    print("Cases that were FAILING (should now use hybrid search):")
    for case in failing_cases:
        use_hybrid = should_use_hybrid_search(case)
        print(f"  - '{case}' -> Hybrid: {use_hybrid}")
        if use_hybrid:
            print(f"    ✅ Will now use hybrid search (should find results)")
        else:
            print(f"    ❌ Still using full-text search (might still fail)")
    
    print("\nCases that were WORKING (should continue to work):")
    for case in working_cases:
        use_hybrid = should_use_hybrid_search(case)
        is_id_like = looks_like_id(case)
        print(f"  - '{case}' -> Hybrid: {use_hybrid}, ID-like: {is_id_like}")
        if use_hybrid:
            print(f"    ✅ Will use hybrid search (even better coverage)")
        else:
            print(f"    ✅ Will continue using full-text search")

if __name__ == "__main__":
    test_patterns()
    print()
    test_specific_cases()