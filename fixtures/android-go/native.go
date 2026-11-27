package main

import "C"

//export probeVersion
func probeVersion() C.int { return 37 }

func main() {}
