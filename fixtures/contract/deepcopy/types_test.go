package deepcopy

import "testing"

func TestGeneratedDeepCopy(t *testing.T) {
	original := &Sample{Labels: map[string]string{"name": "original"}, Values: []string{"original"}}
	copy := original.DeepCopy()
	copy.Labels["name"] = "copy"
	copy.Values[0] = "copy"
	if original.Labels["name"] != "original" || original.Values[0] != "original" {
		t.Fatal("DeepCopy shared mutable fields with the original")
	}
	var into Sample
	original.DeepCopyInto(&into)
	into.Labels["name"] = "into"
	into.Values[0] = "into"
	if original.Labels["name"] != "original" || original.Values[0] != "original" {
		t.Fatal("DeepCopyInto shared mutable fields with the original")
	}
}
