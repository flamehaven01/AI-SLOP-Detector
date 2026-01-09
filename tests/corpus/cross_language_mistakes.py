"""Test corpus for cross-language patterns - AI leaking patterns from other languages."""

# JavaScript patterns
def js_mistakes():
    items = []
    items.push(1)  # [!] Use .append()
    count = items.length  # [!] Use len()
    items.forEach(print)  # [!] Use for loop


# Java patterns
def java_mistakes():
    text1 = "hello"
    text2 = "hello"
    if text1.equals(text2):  # [!] Use ==
        pass
    
    result = obj.toString()  # [!] Use str()
    is_empty = list.isEmpty()  # [!] Use not list


# Ruby patterns  
def ruby_mistakes():
    items.each(lambda x: print(x))  # [!] Use for loop
    if value.nil?():  # [!] Use is None
        pass
    
    first = array.first  # [!] Use array[0]
    last = array.last  # [!] Use array[-1]


# Go patterns
import fmt

def go_mistakes():
    fmt.Println("Hello")  # [!] Use print()
    if value == nil:  # [!] Use is None
        pass


# C# patterns
def csharp_mistakes():
    count = text.Length  # [!] Use len() - capitalized
    lower = text.ToLower()  # [!] Use .lower() - capitalized
    has = list.Contains(item)  # [!] Use in


# PHP patterns
def php_mistakes():
    length = strlen(text)  # [!] Use len()
    array_push(items, item)  # [!] Use .append()
    parts = explode(',', text)  # [!] Use .split()
    joined = implode(',', parts)  # [!] Use .join()


# GOOD EXAMPLES (should NOT trigger)
def python_correct():
    items = []
    items.append(1)  # [+] Correct
    count = len(items)  # [+] Correct
    
    for item in items:  # [+] Correct
        print(item)
    
    text1 = "hello"
    text2 = "hello"
    if text1 == text2:  # [+] Correct
        pass
    
    result = str(obj)  # [+] Correct
    
    if value is None:  # [+] Correct
        pass
    
    lower = text.lower()  # [+] Correct
    parts = text.split(',')  # [+] Correct
    joined = ','.join(parts)  # [+] Correct
