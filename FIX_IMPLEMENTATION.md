# Search Bug Fix Implementation

## Problem Summary

The madoc-search-service was failing to find IIIF manifests with IDs containing the pattern `KCDC_A-005`, while successfully finding `KCDC_B-005` and `KCDC_C-005`. This issue was caused by PostgreSQL's full-text search treating the single letter "A" as a stop word and filtering it out during tokenization of hyphenated words.

## Root Cause

PostgreSQL's English text search configuration processes hyphenated words by creating multiple tokens:
- `KCDC_A-005` → `kcdc_a-005` (full), `kcdc`, ~~`a` (filtered as stop word)~~, `005`
- `KCDC_B-005` → `kcdc_b-005` (full), `kcdc`, `b`, `005`

When searching relied on individual word parts, the missing "a" token caused search failures.

## Implemented Solution

### Quick Fix: Pattern-Based Search Strategy

Modified `search_service/search/parsers.py` to detect ID-like patterns and handle them with exact matching instead of full-text search.

#### Changes Made:

1. **Added pattern detection function** (`looks_like_id`):
   ```python
   def looks_like_id(text):
       """Detect ID patterns like KCDC_A-005 that might have stop word issues"""
       return bool(re.match(r'^[A-Z]+_[A-Z]-\d+$', text.strip(), re.IGNORECASE))
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
- `test_search_fix.py` - Test script to validate the fix
- `SEARCH_BUG_ANALYSIS.md` - Detailed problem analysis
- `search_service/search/management/commands/setup_custom_search_config.py` - Management command for advanced fix

## Testing

Run the test script to validate the fix:
```bash
python3 test_search_fix.py
```

Expected results after fix:
- ✅ `KCDC_A-005` should now return results
- ✅ `KCDC_B-005` should continue to work
- ✅ `KCDC_C-005` should continue to work  
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
- ✅ Fixes the specific search issue with `KCDC_A-005` patterns
- ✅ Maintains existing functionality for regular text searches
- ✅ Minimal performance impact (pattern check is very fast)
- ✅ No database schema changes required

### Considerations:
- 🔍 ID pattern matching uses `icontains` instead of full-text search (slightly different semantics)
- 🔍 Pattern is currently specific to `WORD_LETTER-NUMBER` format (can be extended if needed)

## Future Enhancements

1. **Expand pattern detection** to cover more ID formats if needed
2. **Implement custom text search configuration** for comprehensive fix
3. **Add configuration option** to enable/disable the ID pattern detection
4. **Monitor search performance** and optimize if needed

## Verification Steps

1. Deploy the fix to your environment
2. Test searching for `KCDC_A-005` - should return results
3. Test searching for `KCDC_B-005` and `KCDC_C-005` - should continue working
4. Test regular text searches - should work normally
5. Monitor search performance and accuracy

## Rollback Plan

If issues arise, simply revert the changes to `search_service/search/parsers.py`:
- Remove the `import re` line
- Remove the `looks_like_id()` function  
- Restore the original `if search_string:` logic

The fix is designed to be safe and non-breaking, with easy rollback capability.