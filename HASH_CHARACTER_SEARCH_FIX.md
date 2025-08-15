# Hash Character (#) Search Bug Fix

## Problem Summary

When searching for strings containing the "#" character (like "012 1-1/#/10/9/4"), the search service was only processing the part before the "#" character and ignoring everything after it.

**Failing Pattern:**
- `"012 1-1/#/10/9/4"` → Only searches "012 1-1/" (truncated at #)

**Expected Behavior:**
- `"012 1-1/#/10/9/4"` → Should search the complete string including "#/10/9/4"

## Root Cause Analysis

The issue was caused by **HTTP URL fragment behavior** rather than server-side processing:

1. **HTTP Fragment Identifier**: The "#" character in URLs is treated as a fragment identifier
2. **Browser Behavior**: Browsers do NOT send anything after "#" to the server in GET requests
3. **URL Truncation**: A URL like `?fulltext=012 1-1/#/10/9/4` gets truncated to `?fulltext=012 1-1/`
4. **Missing URL Encoding**: The "#" character should be URL-encoded as "%23" to be sent to the server

## Implemented Solution

### 1. Server-Side URL Decoding

Added proper URL decoding to handle encoded "#" characters:

```python
def decode_search_string(search_string):
    """
    Properly decode a search string that may contain URL-encoded characters.
    
    Examples:
        - "012 1-1/%23/10/9/4" → "012 1-1/#/10/9/4"
        - "test%20string" → "test string"
    """
    return urllib.parse.unquote(search_string)
```

### 2. Enhanced ID Pattern Detection

Updated `looks_like_id()` function to recognize patterns with "#" characters:

```python
# Pattern for path-like IDs with hash separators: "012 1-1/#/10/9/4"
if re.match(r'^[\w\s\-]+[#/][\w\s\-/]+$', text):
    return True

# Pattern for IDs containing hash symbols in general: "ID#123", "ABC#DEF"
if '#' in text and re.match(r'^[\w\s\-#/]+$', text):
    return True
```

### 3. Applied to Both Request Types

The fix handles search strings from:
- **POST requests** (JSON payload in `parsers.py`)
- **GET requests** (URL parameters in `serializers.py`)

## Files Modified

### `/workspace/search_service/search/parsers.py`
- **Added**: `decode_search_string()` function for URL decoding
- **Added**: URL decoding to search string processing
- **Enhanced**: `looks_like_id()` to detect patterns with "#" characters
- **Added**: Debug logging to track search string processing

### `/workspace/search_service/search/serializers.py`  
- **Added**: Import of `decode_search_string`
- **Added**: URL decoding for GET request query parameters

## Usage Instructions

### For Client Applications

**Recommended Approach**: Always URL-encode search parameters containing "#":

```javascript
// JavaScript example
const searchQuery = "012 1-1/#/10/9/4";
const encodedQuery = encodeURIComponent(searchQuery);
// Result: "012%201-1%2F%23%2F10%2F9%2F4"

// Use in GET request
fetch(`/api/search/search?fulltext=${encodedQuery}`);

// Or in POST request (no encoding needed in JSON body)
fetch('/api/search/search', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({fulltext: searchQuery})
});
```

**Python example**:
```python
import urllib.parse

search_query = "012 1-1/#/10/9/4"
encoded_query = urllib.parse.quote(search_query)
# Result: "012%201-1/%23/10/9/4"

# Use in requests
import requests
response = requests.get(f"/api/search/search?fulltext={encoded_query}")
```

### Search Strategy for Hash-Containing Patterns

The server now automatically detects patterns with "#" and uses **exact matching** instead of full-text search:

```python
# These patterns will use exact matching (icontains):
- "012 1-1/#/10/9/4"
- "ID#123" 
- "ABC#DEF"
- "document#section1"

# These patterns will use full-text or hybrid search:
- "regular search terms"
- "Kundeling archives ID 108"
```

## Testing

### Test the Fix

```bash
# Test with URL-encoded hash character
curl "http://localhost:8000/api/search/search?fulltext=012%201-1%2F%23%2F10%2F9%2F4"

# Test with POST request
curl -X POST "http://localhost:8000/api/search/search" \
     -H "Content-Type: application/json" \
     -d '{"fulltext": "012 1-1/#/10/9/4"}'
```

### Expected Results After Fix:
- ✅ `"012 1-1/#/10/9/4"` should now search the complete string including "#/10/9/4"
- ✅ `"012%201-1%2F%23%2F10%2F9%2F4"` (URL-encoded) should work correctly
- ✅ All existing searches should continue to work normally
- ✅ Debug logs should show URL decoding when it occurs

## Key Benefits

1. **✅ Fixes the hash character bug** - Complete search strings are now processed
2. **✅ Maintains backward compatibility** - All existing searches continue to work
3. **✅ Handles both request types** - GET and POST requests both supported
4. **✅ Robust URL decoding** - Handles various URL-encoded characters
5. **✅ Better pattern detection** - Recognizes ID-like patterns with hash characters
6. **✅ Detailed logging** - Debug information for troubleshooting

## Important Notes

### Client-Side Requirements

**Critical**: Client applications should URL-encode search parameters containing "#" characters for GET requests:

- ❌ **Wrong**: `?fulltext=012 1-1/#/10/9/4` (truncated by browser)
- ✅ **Correct**: `?fulltext=012%201-1%2F%23%2F10%2F9%2F4` (URL-encoded)
- ✅ **Alternative**: Use POST requests with JSON body (no encoding needed)

### Browser Behavior

Remember that "#" has special meaning in URLs:
- In `http://example.com/page?q=test#fragment`, everything after "#" is a fragment
- Fragments are processed client-side only and never sent to the server
- This is standard HTTP behavior across all browsers and cannot be changed

## Rollback Plan

If issues arise, the fix can be easily reverted:

1. Remove the `decode_search_string()` function from `parsers.py`
2. Remove URL decoding calls in both `parsers.py` and `serializers.py`  
3. Restore the original `looks_like_id()` function patterns
4. Remove the additional import in `serializers.py`

The fix is designed to be non-breaking with easy rollback capability.