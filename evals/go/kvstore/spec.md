Create an example database store in Go.

The database is a key/value store with typical set/get/delete/search operations supported.
Key/values pairs are stored in-memory and saved to file system, with the key becoming the
file name and value becoming the file content.

Support public REST API for operations.

The number of key/values stored in memory is limited to a configurable number.
If the total number of key/values exceeds this number, the least recently used pairs 
must be evicted from memory.

Limit key sizes to 64 bytes and value sizes to 4MiB. Return errors if API call tries to
exceed the limits. Valid characters for keys are ASCII letters, digits, underscores and hyphens. 
Values can contain any byte sequences.

The "get" operation returns the value as the body of the http response.
If the key is not found, return 404 status code.

The "set" operation sets the pair in memory and returns the API call immediately.
The saving of the key/value pair to the file system is done asynchronously. 
If the saving fails, the key/value pair is removed from memory and an error is logged.

The "search" operation supports searching for word values. The search should return all
keys that have corresponding values containing the search word. To speed up the search,
maintain an in-memory index of words to keys. The index should be updated by a
background goroutine that watches for changes in the key/value pairs and updates the
index accordingly. Words are defined as sequences of characters separated by whitespace.
The search should be case-sensitive.

On startup the database must read the key/value pairs from the file system and populate
the in-memory store and index.

Build, run and verify the example works. Include unit tests. Include documentation. 
Add doc comments to all public types and methods. Follow Effective Go recommendations.

Add makefile with "build" and "test" targets. Make sure "build" target runs all tests.
