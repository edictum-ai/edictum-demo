module github.com/edictum-ai/edictum-demo/adapters/go

go 1.25.0

require github.com/edictum-ai/edictum-go v0.1.0

require gopkg.in/yaml.v3 v3.0.1 // indirect

// During development, replace with local path. Assumes edictum-go is a sibling
// repo: project/edictum-demo/ and project/edictum-go/. Adjust if needed.
replace github.com/edictum-ai/edictum-go => ../../../edictum-go
