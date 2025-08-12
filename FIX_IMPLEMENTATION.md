# Search Bug Fix Implementation

## Problem Summary

The madoc-search-service was failing to find IIIF manifests with ID patterns containing the letter "A":
- **Full IDs**: `KCDC_A-005` (failed) vs `KCDC_B-005` (worked)
- **Partial searches**: `KCDC_A`, `A-005` (failed) vs `KCDC_B`, `B-005` (worked)

This issue was caused by PostgreSQL's full-text search treating the single letter "A" as a stop word and filtering it out during tokenization of hyphenated words and partial searches.

## Root Cause

PostgreSQL's English text search configuration processes hyphenated words by creating multiple tokens:
- `KCDC_A-005` → `kcdc_a-005` (full), `kcdc`, ~~`a` (filtered as stop word)~~, `005`
- `KCDC_B-005` → `kcdc_b-005` (full), `kcdc`, `b`, `005`

When searching relied on individual word parts, the missing "a" token caused search failures.

## Implemented Solution

### Enhanced Fix: Comprehensive Pattern-Based Search Strategy

Modified `search_service/search/parsers.py` to detect various ID-like patterns (both full and partial) and handle them with exact matching instead of full-text search.

#### Changes Made:

1. **Added comprehensive pattern detection function** (`looks_like_id`):
   ```python
   def looks_like_id(text):
       """Detect ID patterns that might have stop word issues"""
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
       
       # Pattern for codes that might contain stop words
       if re.match(r'^[A-Z]+_[A-Z]+$', text, re.IGNORECASE) and len(text.split('_')[-1]) == 1:
           return True
       
       return False
   ```

2. **Modified search logic** to use `icontains` for ID patterns:
   ```python
   if looks_like_id(search_string):
       # Use exact matching to avoid stop word filtering issues
       postfilter_q.append(Q(indexables__indexable__icontains=search_string))
   elif (non_latin_fulltext or is_latin(search_string)) and not search_multiple_fields:
       # Use existing full-text search logic
   ```

#### Files Modified:
- `search_service/search/parsers.py`
  - Added `import re`
  - Added `looks_like_id()` function
  - Modified search string processing logic

#### Files Created:
- `test_enhanced_fix.py` - Enhanced test script to validate the comprehensive fix
- `SEARCH_BUG_ANALYSIS.md` - Detailed problem analysis
- `search_service/search/management/commands/setup_custom_search_config.py` - Management command for advanced fix

## Testing

Run the enhanced test script to validate the comprehensive fix:
```bash
python3 test_enhanced_fix.py
```

Expected results after enhanced fix:
- ✅ `KCDC_A-005` should now return results (original issue)
- ✅ `KCDC_A` should now return results (partial search)
- ✅ `A-005` should now return results (partial search)
- ✅ `KCDC_B`, `B-005` should now work consistently (partial searches)
- ✅ `KCDC_B-005`, `KCDC_C-005` should continue to work  
- ✅ Regular text searches should work normally

## Alternative Solutions

### Advanced Fix: Custom Text Search Configuration

For a more comprehensive solution, you can create a custom PostgreSQL text search configuration:

```bash
python3 search_service/manage.py setup_custom_search_config
```

This creates a `madoc_search` configuration that doesn't filter hyphenated word parts, preventing the stop word issue entirely.

## Impact Assessment

### Positive Impacts:
- ✅ Fixes the complete range of search issues with stop word patterns
- ✅ Handles both full IDs (`KCDC_A-005`) and partial searches (`KCDC_A`, `A-005`)
- ✅ Maintains existing functionality for regular text searches
- ✅ Minimal performance impact (pattern checks are very fast)
- ✅ No database schema changes required
- ✅ Comprehensive coverage of related ID formats

### Considerations:
- 🔍 ID pattern matching uses `icontains` instead of full-text search (slightly different semantics)
- 🔍 Expanded pattern detection is more permissive but targeted to avoid false positives
- 🔍 Covers multiple ID formats to prevent similar issues with other patterns

## Future Enhancements

1. **Expand pattern detection** to cover more ID formats if needed
2. **Implement custom text search configuration** for comprehensive fix
3. **Add configuration option** to enable/disable the ID pattern detection
4. **Monitor search performance** and optimize if needed

## Verification Steps

1. Deploy the enhanced fix to your environment
2. Test searching for `KCDC_A-005` - should return results (original issue)
3. Test searching for `KCDC_A` - should now return results (new fix)
4. Test searching for `A-005` - should now return results (new fix)
5. Test searching for `KCDC_B`, `B-005` - should work consistently
6. Test searching for `KCDC_B-005` and `KCDC_C-005` - should continue working
7. Test regular text searches - should work normally
8. Monitor search performance and accuracy

## Rollback Plan

If issues arise, simply revert the changes to `search_service/search/parsers.py`:
- Remove the `import re` line
- Remove the `looks_like_id()` function  
- Restore the original `if search_string:` logic

The fix is designed to be safe and non-breaking, with easy rollback capability.