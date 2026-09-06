import os
import re
import unittest

import yaml


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_repository_file(*path_parts):
    with open(os.path.join(REPOSITORY_ROOT, *path_parts), encoding="utf-8") as source:
        return source.read()


def referenced_instance_pool_shapes(statement):
    shapes = set()
    if isinstance(statement, dict):
        equality = statement.get("eq")
        if (
            isinstance(equality, list)
            and len(equality) == 2
            and equality[0] == "${instance_pool_shape}"
        ):
            shapes.add(equality[1])
        for value in statement.values():
            shapes.update(referenced_instance_pool_shapes(value))
    elif isinstance(statement, list):
        for value in statement:
            shapes.update(referenced_instance_pool_shapes(value))
    return shapes


class InstancePoolFlexOcpuTests(unittest.TestCase):
    INTEGER_SHAPE_GROUPS = {
        "instance_pool_ocpus": {
            "maximum": 126,
            "default": 64,
            "shapes": {"VM.Standard.E5.Flex", "VM.Standard.E6.Flex"},
        },
        "instance_pool_ocpus_94": {
            "maximum": 94,
            "default": 64,
            "shapes": {"VM.Standard.E6.Ax.Flex"},
        },
        "instance_pool_ocpus_76": {
            "maximum": 76,
            "default": 64,
            "shapes": {"VM.Standard.A1.Flex"},
        },
        "instance_pool_ocpus_64": {
            "maximum": 64,
            "default": 64,
            "shapes": {"VM.Standard.E3.Flex", "VM.Standard.E4.Flex"},
        },
        "instance_pool_ocpus_39": {
            "maximum": 39,
            "default": 39,
            "shapes": {"VM.Standard4.Ax.Flex"},
        },
        "instance_pool_ocpus_32": {
            "maximum": 32,
            "default": 32,
            "shapes": {"VM.Standard3.Flex"},
        },
        "instance_pool_ocpus_18": {
            "maximum": 18,
            "default": 18,
            "shapes": {"VM.Optimized3.Flex"},
        },
    }
    DENSE_IO_SHAPE_GROUPS = {
        "instance_pool_ocpus_denseIO_flex": {
            "enum": [8, 16, 32],
            "shape": "VM.DenseIO.E4.Flex",
        },
        "instance_pool_ocpus_denseIO_e5_flex": {
            "enum": [8, 16, 24, 32, 40, 48],
            "shape": "VM.DenseIO.E5.Flex",
        },
    }

    @classmethod
    def setUpClass(cls):
        cls.schema = yaml.safe_load(read_repository_file("schema.yaml"))
        cls.variables = cls.schema["variables"]
        cls.terraform_variables = read_repository_file("variables.tf")
        cls.locals = read_repository_file("locals.tf")

    def test_integer_shape_groups_have_exact_bounds_and_visibility(self):
        seen_shapes = set()
        for variable_name, expected in self.INTEGER_SHAPE_GROUPS.items():
            variable = self.variables[variable_name]
            self.assertEqual(variable["type"], "integer")
            self.assertEqual(variable["minimum"], 1)
            self.assertEqual(variable["maximum"], expected["maximum"])
            self.assertEqual(variable["default"], expected["default"])
            self.assertLessEqual(variable["default"], variable["maximum"])
            self.assertEqual(
                referenced_instance_pool_shapes(variable["visible"]),
                expected["shapes"],
            )
            self.assertTrue(seen_shapes.isdisjoint(expected["shapes"]))
            seen_shapes.update(expected["shapes"])

        self.assertEqual(
            seen_shapes,
            set().union(
                *(group["shapes"] for group in self.INTEGER_SHAPE_GROUPS.values())
            ),
        )

    def test_dense_io_shape_groups_have_exact_choices(self):
        for variable_name, expected in self.DENSE_IO_SHAPE_GROUPS.items():
            variable = self.variables[variable_name]
            self.assertEqual(variable["type"], "enum")
            self.assertEqual(variable["enum"], expected["enum"])
            self.assertEqual(
                referenced_instance_pool_shapes(variable["visible"]),
                {expected["shape"]},
            )

    def test_all_shape_group_variables_are_declared_and_shown_in_the_ui(self):
        variable_names = set(self.INTEGER_SHAPE_GROUPS) | set(
            self.DENSE_IO_SHAPE_GROUPS
        )
        compute_group = next(
            group
            for group in self.schema["variableGroups"]
            if group["title"] == "計算ノードで利用するインスタンス"
        )

        for variable_name in variable_names:
            self.assertIn("${" + variable_name + "}", compute_group["variables"])
            self.assertRegex(
                self.terraform_variables,
                rf'variable\s+"{re.escape(variable_name)}"\s*\{{',
            )

    def test_terraform_shape_table_uses_the_matching_bounded_variable(self):
        expected_mappings = {}
        for variable_name, group in self.INTEGER_SHAPE_GROUPS.items():
            for shape in group["shapes"]:
                expected_mappings[shape] = variable_name
        for variable_name, group in self.DENSE_IO_SHAPE_GROUPS.items():
            expected_mappings[group["shape"]] = variable_name

        for shape, variable_name in expected_mappings.items():
            self.assertRegex(
                self.locals,
                rf'"{re.escape(shape)}"\s*=\s*var\.{re.escape(variable_name)}\b',
            )

        self.assertIn(
            "lookup(local.instance_pool_flex_ocpus_by_shape, "
            "local.shape, var.instance_pool_ocpus)",
            self.locals,
        )


if __name__ == "__main__":
    unittest.main()
