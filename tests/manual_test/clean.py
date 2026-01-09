"""
This file contains standard logic with minimal jargon.
It should receive a low Inflation Score (ICR) and a 'PASS' status.
"""

def calculate_sum(numbers):
    """Calculate sum of numbers."""
    total = 0
    for n in numbers:
        total += n
    return total

class DataProcessor:
    """Process simple data."""
    
    def process(self, data):
        """Process data items."""
        results = []
        for item in data:
            if item > 0:
                results.append(item * 2)
        return results
