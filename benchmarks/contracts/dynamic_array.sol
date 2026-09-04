pragma solidity ^0.8.0;
contract DynamicArrayFixture { uint256[] internal values; function push(uint256 value) external { values.push(value); } function length() external view returns (uint256) { return values.length; } }
