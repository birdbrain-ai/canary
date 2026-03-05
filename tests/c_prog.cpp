#include <iostream>
// #include <cstdlib>
// #include <vector>

// using namespace std;

constexpr int ROWS = 10000;
constexpr int COLS = 47;

// std::vector<int> hi(std::vector<int> A, std::vector<int> B) {
//   std::vector<int> C;
//     for (int i = 0; i < A.size(); i++) {
//         C[i] = A[i] + B[i];
//     }
//     return C;
// }

// Likely vectorizes
void vec_friendly(int A[ROWS][COLS], int c) {
  for (int i = 0; i < ROWS - 2; i += 2)
#pragma clang loop vectorize(enable)
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

// Triggers SLP vectorization on the latest version of clang
int ih(int* __restrict a, int* __restrict b) {
    int a_i = a[0] - 35;
    int a_i2 = a[1] + 35;
    int b_i = b[0] - 35;
    int b_i2 = b[1] + 35;
    int c_i = b[2] + 35;
    int ci2 = b[3] - 35;
    int d_i = a[2] + 35;
    int d_i2 = a[3] - 35;
    return a_i + a_i2 + b_i + b_i2 + c_i + ci2 + d_i + d_i2;
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
