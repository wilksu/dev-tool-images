// Package deepcopy contains a minimal fixture for controller-gen.
//
// +kubebuilder:object:generate=true
package deepcopy

// Sample exercises generated copying of reference-valued fields.
type Sample struct {
	Labels map[string]string
	Values []string
}
