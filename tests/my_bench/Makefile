COMPILER ?= clang

ifeq ($(COMPILER),clang)
CXX = clang++
CXXFLAGS = -O3 -fsave-optimization-record -Rpass=loop-vectorize -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize
else
CXX = icpx
CXXFLAGS = -O3 -qopt-report=5
endif

TARGET = c_prog

all: $(TARGET)

$(TARGET): c_prog.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(TARGET) *.opt.yaml *.optrpt
