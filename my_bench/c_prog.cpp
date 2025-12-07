#include <iostream>
#include <cstdlib>
#include <vector>

using namespace std;

constexpr int ROWS = 10000;
constexpr int COLS = 47;

std::vector<int> hi(std::vector<int> A, std::vector<int> B) {
  std::vector<int> C;
    for (int i = 0; i < A.size(); i++) {
        C[i] = A[i] + B[i];
    }
    return C;
}

// Likely vectorizes
void vec_friendly(int A[ROWS][COLS], int c) {
  for (int i = 0; i < ROWS - 2; i += 2)
	for (int j = 0; j < COLS; ++j) {
	  A[i][j] += 50 + c;
	  A[i + 1][j] += 49 + c;
	}
}

// Hard to vectorize because of a loop-carried dependence
void hard_to_vectorize(int A[ROWS][COLS], int c) {
  for (int i = 0; i < ROWS; ++i) {
	for (int j = 1; j < COLS; ++j) {
	  A[i][j] += A[i][j - 1] + c;
	}
  }
}

int main() {
  int repeats = 500;
  
  static int A[ROWS][COLS];  
  for (int i = 0; i < ROWS; ++i) {
    for (int j = 0; j < COLS; ++j) {
      A[i][j] = j;
    }
  }
  
  for (int r = 0; r < repeats; ++r) {

	vec_friendly(A, r); 
	hard_to_vectorize(A, r); 
  }

  std::cout << "Hi\n";
  
  return 0;
}
